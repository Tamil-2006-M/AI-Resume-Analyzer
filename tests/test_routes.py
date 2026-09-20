"""
Tests for the Flask routes in app.py

These are "integration tests": they exercise the whole stack - routing,
validation, PDF parsing, scoring, the AI fallback and template
rendering - through the same HTTP interface a real browser uses.
"""

import pytest


class TestHomePage:
    def test_loads(self, client):
        assert client.get("/").status_code == 200

    def test_has_the_upload_form(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'enctype="multipart/form-data"' in html
        assert 'name="resume"' in html

    def test_shows_the_ats_disclaimer(self, client):
        """
        Required by the project brief: the score must never be presented
        as a real company's ATS result.
        """
        html = client.get("/").get_data(as_text=True).lower()
        assert "estimated" in html


class TestHealth:
    def test_returns_json(self, client):
        """
        Hosting platforms poll this endpoint to decide whether the app
        is alive, so it must stay cheap and must never touch the
        database or the AI.
        """
        data = client.get("/health").get_json()
        assert data["status"] == "ok"
        assert data["version"]

    def test_is_fast_and_dependency_free(self, client):
        """It must answer even with MySQL and the AI switched off."""
        assert client.get("/health").status_code == 200


class TestHistoryPage:
    def test_loads_even_with_the_database_off(self, client):
        """
        The page must degrade gracefully. A crash here would be a demo
        failure the moment MySQL is not running.
        """
        response = client.get("/history")
        assert response.status_code == 200
        assert "Database not connected" in response.get_data(as_text=True)

    def test_shows_setup_instructions(self, client):
        html = client.get("/history").get_data(as_text=True)
        assert "database.db --init" in html


class TestErrorPages:
    def test_unknown_url_is_a_styled_404(self, client):
        response = client.get("/no-such-page")
        assert response.status_code == 404
        assert "Page not found" in response.get_data(as_text=True)

    def test_get_on_upload_is_405(self, client):
        assert client.get("/upload").status_code == 405

    def test_errors_never_leak_a_traceback(self, client):
        """
        A stack trace tells an attacker your file paths, your library
        versions and often your database structure.
        """
        html = client.get("/no-such-page").get_data(as_text=True)
        for leak in ["Traceback", "File \"", "werkzeug", "site-packages"]:
            assert leak not in html


class TestUploadValidation:
    def test_a_good_pdf_is_accepted(self, upload):
        response = upload("good.pdf")
        assert response.status_code == 200
        assert "Your resume report" in response.get_data(as_text=True)

    @pytest.mark.parametrize("filename", [
        "scanned.pdf",     # no text - a scan
        "locked.pdf",      # password protected
        "fake.pdf",        # a text file renamed
        "corrupt.pdf",     # valid header, broken body
        "empty.pdf",       # zero bytes
    ])
    def test_bad_pdfs_are_rejected_with_a_redirect(self, upload, filename):
        response = upload(filename)
        assert response.status_code == 302, filename

    def test_oversized_file_is_rejected(self, upload):
        """Flask enforces MAX_CONTENT_LENGTH before reading the body."""
        response = upload("huge.pdf")
        assert response.status_code in (302, 413)

    def test_wrong_content_type_is_rejected(self, upload):
        response = upload("good.pdf", content_type="text/plain")
        assert response.status_code == 302

    def test_no_file_at_all_is_rejected(self, csrf_client):
        test_client, token = csrf_client
        response = test_client.post("/upload", data={"csrf_token": token},
                                    content_type="multipart/form-data")
        assert response.status_code == 302

    def test_a_rejected_upload_is_not_kept_on_disk(self, upload, flask_app):
        """
        There is no reason to store a resume we could not read, and a
        folder that only ever grows is a disk-space outage waiting to
        happen.
        """
        import os
        folder = flask_app.config["UPLOAD_FOLDER"]
        before = set(os.listdir(folder))
        upload("corrupt.pdf")
        after = set(os.listdir(folder))
        assert after == before


class TestResultPage:
    def test_shows_the_ats_score(self, upload):
        html = upload("good.pdf").get_data(as_text=True)
        assert "ESTIMATED ATS SCORE" in html
        assert "score-ring" in html

    def test_the_score_carries_its_disclaimer(self, upload):
        """
        DO NOT DELETE THIS DISCLAIMER.

        The project brief requires it, and it is simply honest: this
        score comes from our own published rules, not from Workday,
        Taleo, Greenhouse or any other real ATS. Presenting an invented
        number as a real company's verdict would mislead someone about
        their job prospects.

        This test exists because a very similar-looking leftover banner
        was correctly removed from this page, and the next person
        tidying up could easily remove this one too.
        """
        import re
        html = upload("good.pdf").get_data(as_text=True)

        # The sentence is wrapped across several lines in the template,
        # so collapse all whitespace before looking for it. Asserting on
        # the raw HTML would break the moment someone re-indents the file.
        flat = re.sub(r"\s+", " ", html).lower()

        assert "score-disclaimer" in html
        assert "estimated" in flat
        assert "not the score of any specific company" in flat

    def test_shows_skills_and_sections(self, upload):
        html = upload("good.pdf").get_data(as_text=True)
        assert "Technical Skills" in html
        assert "Resume Sections" in html

    def test_shows_the_ai_card(self, upload):
        """AI is off in tests, so this must be the rule-based fallback."""
        html = upload("good.pdf").get_data(as_text=True)
        assert "AI Resume Review" in html
        assert "Rule-based fallback" in html

    def test_job_match_only_appears_with_a_job_description(self, upload):
        without = upload("good.pdf").get_data(as_text=True)
        assert "Want a Job Match score?" in without

        with_jd = upload(
            "good.pdf",
            job_description="Python developer with Flask, SQL, AWS and Docker."
        ).get_data(as_text=True)
        assert "JOB MATCH" in with_jd
        assert "Resume vs Job Description" in with_jd

    def test_charts_are_rendered(self, upload):
        html = upload("good.pdf").get_data(as_text=True)
        assert 'id="chartData"' in html
        assert 'id="skillsChart"' in html
        assert "View as a table" in html

    def test_every_template_tag_was_rendered(self, upload):
        """A leftover {{ }} means a typo in the template."""
        html = upload("good.pdf").get_data(as_text=True)
        assert "{{" not in html
        assert "{%" not in html


class TestXssProtection:
    def test_the_job_description_is_escaped(self, upload):
        """
        The job description is user input echoed back to the page. If it
        were not escaped, anyone could run JavaScript in a viewer's
        browser.
        """
        payload = ('<script>alert("xss")</script> Python '
                   '<img src=x onerror=alert(1)> Flask')
        html = upload("good.pdf", job_description=payload).get_data(as_text=True)

        assert "<script>alert" not in html
        assert "<img src=x" not in html
        assert "&lt;script&gt;" in html

    def test_skills_are_still_found_in_a_hostile_input(self, upload):
        payload = "<script>bad()</script> We need Python and Flask."
        html = upload("good.pdf", job_description=payload).get_data(as_text=True)
        assert "JOB MATCH" in html

    def test_a_hostile_filename_is_made_safe(self, csrf_client, pdf_dir):
        """secure_filename must strip the path traversal attempt."""
        test_client, token = csrf_client
        path = pdf_dir / "good.pdf"
        response = test_client.post("/upload", data={
            "resume": (path.open("rb"), "../../app.py.pdf",
                       "application/pdf"),
            "csrf_token": token,
        }, content_type="multipart/form-data")
        assert response.status_code == 200

        import os
        # The traversal must not have escaped the uploads folder.
        assert os.path.exists("app.py")
        assert not os.path.exists("app.py.pdf")


class TestJobDescriptionLimits:
    def test_a_very_long_job_description_is_trimmed(self, upload):
        html = upload("good.pdf",
                      job_description="Python Flask " * 5000
                      ).get_data(as_text=True)
        assert "JOB MATCH" in html      # trimmed, not rejected

    def test_unicode_is_handled(self, upload):
        response = upload("good.pdf",
                          job_description="Python разработчик 🚀 Flask 日本")
        assert response.status_code == 200


class TestNoLeftoverDevelopmentText:
    """
    The result page was built in ten phases, and each phase left a
    "Phase N checkpoint" note behind. One survived to the finished app
    and told users that job description matching was "added in the next
    phase" - which was both confusing and false.

    This test makes sure build-time language can never reach a user again.
    """

    def test_no_phase_numbers_are_shown_to_the_user(self, upload):
        import re
        html = upload("good.pdf").get_data(as_text=True)

        # HTML comments are fine - they document the build history and
        # the browser never displays them. Strip them, then check what
        # a visitor would actually read.
        visible = re.sub(r"<!--.*?-->", "", html, flags=re.S)
        assert not re.search(r"[Pp]hase\s+\d+", visible)

    def test_no_checkpoint_banner(self, upload):
        assert "checkpoint" not in upload("good.pdf").get_data(as_text=True).lower()
