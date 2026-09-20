"""
tests/conftest.py
=================
Shared setup for every test file.

pytest loads this automatically - no import needed. Anything defined
here with @pytest.fixture can be requested by name in any test:

    def test_something(client):      # <- pytest passes the fixture in
        ...

Two things this file is careful about
-------------------------------------
1. THE TESTS NEVER TOUCH YOUR REAL SETUP.
   Environment variables are set BEFORE app.py is imported, so the test
   run always has the database and the AI switched off. Tests that need
   a live MySQL server or a paid API key are not tests - they are
   experiments, and they fail on a marker's machine.

2. THE TEST PDFs ARE BUILT, NOT SHIPPED.
   We generate them with PyMuPDF into a temporary folder. Committing
   binary fixtures to Git bloats the repository and makes it impossible
   to see in a diff what changed.
"""

import os
import sys
import pathlib

import pytest

# ---------------------------------------------------------------------
# Put the project root on the import path
# ---------------------------------------------------------------------
# So "import app" works when pytest is run from anywhere.
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------
# Test configuration - MUST be set before app.py is imported
# ---------------------------------------------------------------------
# app.py calls load_dotenv() at import time, and load_dotenv does NOT
# overwrite variables that already exist. So setting them here wins.
os.environ["DB_ENABLED"] = "false"       # no MySQL needed
os.environ["AI_ENABLED"] = "false"       # no API key needed, no cost
os.environ["FLASK_DEBUG"] = "false"      # exercise the real error pages
os.environ["RATE_LIMIT_MAX"] = "0"       # off by default; one test turns it on
os.environ["SECRET_KEY"] = "test-secret-key-not-used-in-production"
os.environ["UPLOAD_RETENTION_HOURS"] = "0"   # do not delete during a test run

import app as app_module          # noqa: E402  (import after the env setup)
import security                   # noqa: E402


# =====================================================================
# Building test PDFs
# =====================================================================

def _make_pdf(path, lines):
    """Write a simple one-page text PDF."""
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    y = 55
    for text, size in lines:
        if text:
            page.insert_text((45, y), text, fontsize=size)
        y += size + 5
    document.save(str(path))
    document.close()
    return path


GOOD_RESUME_LINES = [
    ("PRIYA VENKATESAN", 15),
    ("Chennai, India | priya.v99@example.com | +91-98400-12345", 8),
    ("linkedin.com/in/priyav  |  github.com/priyav  |  priyabuilds.dev", 8),
    ("", 8),
    ("CAREER OBJECTIVE", 11),
    ("Final year CSE student seeking a backend developer role.", 9),
    ("", 8),
    ("EDUCATION", 11),
    ("B.E. Computer Science Engineering, Anna University, 2022 - 2026", 9),
    ("CGPA: 8.7 / 10", 9),
    ("", 8),
    ("TECHNICAL SKILLS", 11),
    ("Languages: Python, C, C++, Java, JavaScript, R", 9),
    ("Web: HTML5, CSS3, React.js, Node.js, Flask, REST APIs", 9),
    ("Databases: MySQL, MongoDB, PostgreSQL", 9),
    ("Cloud & Tools: AWS, Docker, Git, GitHub, Postman", 9),
    ("", 8),
    ("Work Experience", 11),
    ("Backend Intern, Example Corp, Jun 2025 - Aug 2025", 9),
    ("- Developed 12 REST API endpoints using Flask and MySQL.", 9),
    ("- Reduced average query response time by 40% through indexing.", 9),
    ("", 8),
    ("ACADEMIC PROJECTS", 11),
    ("- Smart Attendance System - Built with Python, OpenCV and MySQL.", 9),
    ("- Served 1200 students across 3 departments.", 9),
    ("", 8),
    ("CERTIFICATIONS", 11),
    ("- AWS Certified Cloud Practitioner, 2025", 9),
    ("- Machine Learning Specialization, Coursera, 2024", 9),
    ("", 8),
    ("ACHIEVEMENTS & AWARDS", 11),
    ("- Winner, Smart India Hackathon 2025 among 250 teams.", 9),
    ("", 8),
    ("Strong communication skills, leadership and problem solving.", 9),
]


@pytest.fixture(scope="session")
def pdf_dir(tmp_path_factory):
    """
    Build every test PDF once per test run.

    scope="session" means this runs ONCE, not before every test. Making
    ten PDFs for each of forty tests would make the suite needlessly slow.
    """
    directory = tmp_path_factory.mktemp("pdfs")

    # 1. A complete, well-structured resume.
    _make_pdf(directory / "good.pdf", GOOD_RESUME_LINES)

    # 2. A sparse resume.
    #
    # It has to be long enough to clear pdf_parser's MIN_USABLE_CHARS
    # (100 characters), or extraction rejects it as a scanned page and
    # we never reach the scorer at all. So it is WEAK, not TINY: only
    # three of the eight sections, no phone, no LinkedIn or GitHub, no
    # projects, no certifications, no numbers, and no action verbs.
    _make_pdf(directory / "weak.pdf", [
        ("John Smith", 14),
        ("john@example.com", 9),
        ("", 8),
        ("EDUCATION", 11),
        ("B.Sc Computer Science from a university, finished recently.", 9),
        ("", 8),
        ("SKILLS", 11),
        ("Python and HTML. Also a bit of general computer knowledge.", 9),
        ("", 8),
        ("OBJECTIVE", 11),
        ("Was responsible for various tasks. A hardworking team player", 9),
        ("looking for a challenging role in a dynamic organization.", 9),
    ])

    # 3. A PDF with no text at all - what a scanned resume looks like.
    import pymupdf
    document = pymupdf.open()
    document.new_page()
    document.save(str(directory / "scanned.pdf"))
    document.close()

    # 4. Password protected.
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((60, 70), "Locked document for testing.", fontsize=11)
    document.save(str(directory / "locked.pdf"),
                  encryption=pymupdf.PDF_ENCRYPT_AES_256,
                  owner_pw="owner", user_pw="user")
    document.close()

    # 5. Not a PDF at all, just renamed.
    (directory / "fake.pdf").write_text(
        "I am plain text pretending to be a PDF.", encoding="utf-8")

    # 6. Valid %PDF- header, garbage body.
    (directory / "corrupt.pdf").write_bytes(
        b"%PDF-1.4\nthis body is complete garbage\n")

    # 7. Zero bytes.
    (directory / "empty.pdf").write_bytes(b"")

    # 8. Over the 5 MB limit.
    big = (directory / "huge.pdf")
    big.write_bytes((directory / "good.pdf").read_bytes()
                    + b"\n% padding " + b"x" * (6 * 1024 * 1024))

    return directory


@pytest.fixture(scope="session")
def good_text(pdf_dir):
    """The extracted text of the good resume - used by many tests."""
    from services.pdf_parser import extract_text_from_pdf
    return extract_text_from_pdf(str(pdf_dir / "good.pdf"))["text"]


@pytest.fixture(scope="session")
def parsed_good(good_text):
    """The good resume, parsed."""
    from services.resume_parser import parse_resume
    return parse_resume(good_text)


@pytest.fixture(scope="session")
def ats_good(parsed_good):
    """The good resume's ATS report."""
    from services.ats_scorer import calculate_ats_score
    return calculate_ats_score(parsed_good)


# =====================================================================
# The Flask test client
# =====================================================================

@pytest.fixture
def flask_app():
    """
    The Flask application, configured for testing.

    TESTING=True makes Flask propagate exceptions instead of hiding them
    behind a 500 page, so a broken test shows the real traceback.
    """
    app_module.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,        # we roll our own; see csrf_client
        SERVER_NAME=None,
    )
    # Each test starts with a clean rate-limit counter, otherwise the
    # order tests run in would change their results.
    security.reset_rate_limits()
    yield app_module.app
    security.reset_rate_limits()


@pytest.fixture
def client(flask_app):
    """A fake browser that can call our routes without a real server."""
    return flask_app.test_client()


@pytest.fixture
def csrf_client(client):
    """
    A test client that already holds a valid CSRF token.

    Real browsers get the token by loading the home page first, so the
    test does exactly that. The token is returned alongside the client
    so a test can post with it.
    """
    response = client.get("/")
    assert response.status_code == 200

    # Pull the token out of the rendered form, the same way a browser
    # would read it.
    import re
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"',
                      response.get_data(as_text=True))
    assert match, "The home page did not render a CSRF token"

    return client, match.group(1)


@pytest.fixture
def upload(csrf_client, pdf_dir):
    """
    A helper that posts a PDF to /upload the way a browser would.

    Usage inside a test:

        response = upload("good.pdf")
        response = upload("good.pdf", job_description="Python Flask")
        response = upload("good.pdf", with_csrf=False)
    """
    test_client, token = csrf_client

    def _upload(filename, job_description="", with_csrf=True,
                content_type="application/pdf"):
        path = pdf_dir / filename
        data = {
            "resume": (path.open("rb"), filename, content_type),
            "job_description": job_description,
        }
        if with_csrf:
            data["csrf_token"] = token

        return test_client.post("/upload", data=data,
                                content_type="multipart/form-data")

    return _upload
