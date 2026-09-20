"""
Tests for security.py

A security control that is not tested is a security control you only
*think* you have. Each test below is the attack it prevents, written
down.
"""

import os
import time

import pytest

import security


class TestCsrf:
    def test_a_token_is_rendered_into_the_form(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'name="csrf_token"' in html

    def test_the_same_session_gets_the_same_token(self, client):
        import re
        pattern = r'name="csrf_token"\s+value="([^"]+)"'
        first = re.search(pattern, client.get("/").get_data(as_text=True))
        second = re.search(pattern, client.get("/").get_data(as_text=True))
        assert first.group(1) == second.group(1)

    def test_upload_without_a_token_is_rejected(self, upload):
        """This is the forged-form attack. It must not reach the parser."""
        response = upload("good.pdf", with_csrf=False)
        assert response.status_code == 400

    def test_upload_with_a_wrong_token_is_rejected(self, csrf_client, pdf_dir):
        test_client, _real_token = csrf_client
        path = pdf_dir / "good.pdf"
        response = test_client.post("/upload", data={
            "resume": (path.open("rb"), "good.pdf", "application/pdf"),
            "csrf_token": "clearly-not-the-right-token",
        }, content_type="multipart/form-data")
        assert response.status_code == 400

    def test_upload_with_the_right_token_is_accepted(self, upload):
        assert upload("good.pdf").status_code == 200

    def test_the_error_page_does_not_say_which_part_failed(self, upload):
        """
        Telling an attacker whether the token was missing, wrong or
        expired helps them work out how to pass the check.
        """
        html = upload("good.pdf", with_csrf=False).get_data(as_text=True)
        assert "session expired" in html.lower()
        for leak in ["missing", "invalid token", "mismatch"]:
            assert leak not in html.lower()


class TestSecurityHeaders:
    def test_every_header_is_present(self, client):
        headers = client.get("/").headers
        for name in ["Content-Security-Policy", "X-Content-Type-Options",
                     "X-Frame-Options", "Referrer-Policy",
                     "Permissions-Policy"]:
            assert name in headers, name

    def test_clickjacking_is_blocked(self, client):
        assert client.get("/").headers["X-Frame-Options"] == "DENY"

    def test_mime_sniffing_is_blocked(self, client):
        assert client.get("/").headers["X-Content-Type-Options"] == "nosniff"

    def test_csp_blocks_inline_scripts(self, client):
        """
        The whole point of our CSP. If 'unsafe-inline' ever appears in
        script-src, an injected <script> would run and the policy would
        be worth nothing.
        """
        csp = client.get("/").headers["Content-Security-Policy"]
        script_src = [part for part in csp.split(";")
                      if part.strip().startswith("script-src")][0]
        assert "'unsafe-inline'" not in script_src
        assert "'nonce-" in script_src

    def test_csp_allows_the_cdn_we_actually_use(self, client):
        csp = client.get("/").headers["Content-Security-Policy"]
        assert "https://cdn.jsdelivr.net" in csp

    def test_the_nonce_is_different_on_every_response(self, client):
        first = client.get("/").headers["Content-Security-Policy"]
        second = client.get("/").headers["Content-Security-Policy"]
        assert first != second, "a reused nonce is no better than none"

    def test_hsts_is_not_sent_over_plain_http(self, client):
        """
        Sending HSTS from a local http:// dev server would lock the
        browser out of http://localhost for a year.
        """
        assert "Strict-Transport-Security" not in client.get("/").headers


class TestRateLimiting:
    def test_off_when_the_limit_is_zero(self):
        security.reset_rate_limits()
        os.environ["RATE_LIMIT_MAX"] = "0"
        for _ in range(50):
            allowed, _wait = security.check_rate_limit()
            assert allowed

    def test_blocks_after_the_limit(self, flask_app):
        security.reset_rate_limits()
        with flask_app.test_request_context("/"):
            for _ in range(3):
                allowed, _wait = security.check_rate_limit(3, 60)
                assert allowed
            allowed, wait = security.check_rate_limit(3, 60)
            assert allowed is False
            assert wait > 0

    def test_the_window_slides(self, flask_app):
        """Old requests drop out, so the limit is not permanent."""
        security.reset_rate_limits()
        with flask_app.test_request_context("/"):
            assert security.check_rate_limit(1, 1)[0] is True
            assert security.check_rate_limit(1, 1)[0] is False
            time.sleep(1.1)
            assert security.check_rate_limit(1, 1)[0] is True

    def test_the_route_returns_429_with_retry_after(self, flask_app, upload,
                                                    monkeypatch):
        security.reset_rate_limits()
        monkeypatch.setenv("RATE_LIMIT_MAX", "2")
        monkeypatch.setenv("RATE_LIMIT_WINDOW", "60")

        assert upload("good.pdf").status_code == 200
        assert upload("good.pdf").status_code == 200

        blocked = upload("good.pdf")
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
        assert int(blocked.headers["Retry-After"]) > 0


class TestUploadRetention:
    def test_deletes_files_older_than_the_cutoff(self, tmp_path):
        old = tmp_path / "old.pdf"
        new = tmp_path / "new.pdf"
        old.write_bytes(b"%PDF-1.4 old")
        new.write_bytes(b"%PDF-1.4 new")

        # Backdate the old file by two days.
        two_days_ago = time.time() - (48 * 3600)
        os.utime(old, (two_days_ago, two_days_ago))

        deleted = security.cleanup_old_uploads(str(tmp_path), max_age_hours=24)
        assert deleted == 1
        assert not old.exists()
        assert new.exists()

    def test_zero_hours_means_keep_forever(self, tmp_path):
        keep = tmp_path / "keep.pdf"
        keep.write_bytes(b"%PDF-1.4")
        os.utime(keep, (0, 0))          # 1970 - as old as it gets
        assert security.cleanup_old_uploads(str(tmp_path), 0) == 0
        assert keep.exists()

    def test_never_touches_non_pdf_files(self, tmp_path):
        gitkeep = tmp_path / ".gitkeep"
        gitkeep.write_text("")
        os.utime(gitkeep, (0, 0))
        security.cleanup_old_uploads(str(tmp_path), max_age_hours=1)
        assert gitkeep.exists()

    def test_missing_folder_is_not_an_error(self):
        assert security.cleanup_old_uploads("no/such/folder", 24) == 0


class TestProductionSafetyCheck:
    def test_flags_debug_on_a_public_address(self, flask_app, monkeypatch):
        monkeypatch.setenv("FLASK_DEBUG", "True")
        monkeypatch.setenv("HOST", "0.0.0.0")
        problems = security.check_production_safety(flask_app)
        assert any("FLASK_DEBUG" in p for p in problems)

    def test_flags_the_default_secret_key(self, flask_app, monkeypatch):
        monkeypatch.setitem(flask_app.config, "SECRET_KEY",
                            "dev-secret-change-me")
        problems = security.check_production_safety(flask_app)
        assert any("SECRET_KEY" in p for p in problems)

    def test_quiet_when_settings_are_sensible(self, flask_app, monkeypatch):
        monkeypatch.setenv("FLASK_DEBUG", "False")
        monkeypatch.setenv("HOST", "127.0.0.1")
        monkeypatch.setenv("DB_PASSWORD", "a-long-unguessable-password")
        monkeypatch.setitem(flask_app.config, "SECRET_KEY", "a" * 48)
        assert security.check_production_safety(flask_app) == []
