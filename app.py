"""
app.py
======
Main entry point of the AI Resume Analyzer web application.

What this file does (in simple words):
1. Creates the Flask application object.
2. Loads secret settings (like SECRET_KEY) from the .env file.
3. Defines the URL routes (which URL shows which page).
4. Validates and stores uploaded PDF resumes.
5. Starts the development web server when you run: python app.py

Phase 1 - home page.
Phase 2 - PDF upload, validation and text extraction.
Phase 3 - resume parsing: contact details, sections and skills.
Phase 4 - ATS-style scoring out of 100.
Phase 5 - LLM analysis and improvement suggestions.
Phase 6 - job description matching.
Phase 7 - saving every analysis to MySQL.
Phase 8 - dashboard, charts and UI polish.
Phase 9 - security hardening, error handling, tests.
Phase 10 - documentation, deployment, release 1.0.
"""

import os
import uuid
import secrets
import logging
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, session, g, abort)
from werkzeug.utils import secure_filename

# Our own module. The "services" folder is a Python package because it
# contains an __init__.py file, so we can import from it like this.
from services.pdf_parser import (
    extract_text_from_pdf,
    PDFError,
    InvalidPDFError,
    EncryptedPDFError,
    EmptyPDFError,
)
from services.resume_parser import parse_resume
from services.ats_scorer import calculate_ats_score
from services.ai_analyzer import analyze_resume
from services.job_matcher import match_resume_to_job

# The database package. Like the AI layer, every function here is
# written so that a missing or unreachable MySQL server never breaks
# the page - it simply means the analysis is not saved.
from database import db

# The defensive layer: CSRF, security headers, rate limiting, cleanup.
import security

# ---------------------------------------------------------------------
# STEP 1: Load environment variables from the .env file
# ---------------------------------------------------------------------
# load_dotenv() reads the ".env" file sitting next to this app.py and puts
# every KEY=VALUE line into the operating system environment.
# After this call we can read them using os.getenv("KEY").
# This is how we keep passwords and API keys OUT of the source code.
load_dotenv()


# ---------------------------------------------------------------------
# STEP 2: Create the Flask application
# ---------------------------------------------------------------------
# __name__ tells Flask where the app lives so it can find the
# "templates" folder (HTML files) and the "static" folder (CSS/JS/images).
app = Flask(__name__)

# The SECRET_KEY is used by Flask to sign session cookies and flash messages.
# We read it from .env. The fallback value is ONLY for local development.
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")

# Base folder of the project (absolute path). Using absolute paths means
# the app works no matter which folder you started it from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Folder where uploaded resumes are stored.
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Create the uploads folder automatically if it does not exist yet.
# exist_ok=True means "do not crash if it is already there".
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Maximum upload size = 5 MB.
# Flask checks this BEFORE reading the file into memory, so a huge upload
# cannot fill up the server's RAM. It raises a 413 error, which we handle
# at the bottom of this file.
MAX_FILE_SIZE_MB = 5
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_MB * 1024 * 1024

# The only file extension we accept.
ALLOWED_EXTENSIONS = {".pdf"}

# Longest job description we accept. Anything beyond this is trimmed.
# Without a cap, a user could paste a whole book and we would send it
# to the AI API - slow, and expensive in tokens.
MAX_JOB_DESCRIPTION_CHARS = 5000

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
# Two destinations:
#   * the terminal, so you see what is happening while developing
#   * logs/app.log, so problems are still there tomorrow morning
#
# RotatingFileHandler caps the file at 1 MB and keeps 3 old copies. A
# log file that grows without limit will eventually fill the disk and
# take the whole server down - a surprisingly common outage cause.
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_console = logging.StreamHandler()
_console.setFormatter(_formatter)

_logfile = RotatingFileHandler(
    os.path.join(LOG_DIR, "app.log"),
    maxBytes=1_000_000,     # 1 MB
    backupCount=3,
    encoding="utf-8",
)
_logfile.setFormatter(_formatter)

_root = logging.getLogger()
_root.setLevel(logging.INFO)
# Clear first, so re-importing this module during tests does not attach
# the same handlers twice and print every line two or three times.
_root.handlers.clear()
_root.addHandler(_console)
_root.addHandler(_logfile)


# ---------------------------------------------------------------------
# Session cookie hardening
# ---------------------------------------------------------------------
# HTTPONLY  - JavaScript cannot read the cookie, so a cross-site
#             scripting bug cannot steal the session.
# SAMESITE  - the browser will not send the cookie on a request started
#             by another website. This is a second, independent layer of
#             CSRF defence on top of our token.
# SECURE    - only send the cookie over HTTPS. Switched on automatically
#             when debug mode is off, because a local dev server is
#             plain http and the cookie would never be sent at all.
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("FLASK_DEBUG", "True").strip().lower() != "true")


# ---------------------------------------------------------------------
# STEP 3: Small helper functions
# ---------------------------------------------------------------------

def has_allowed_extension(filename):
    """
    Return True if the filename ends with .pdf (case does not matter).

    os.path.splitext("Resume.PDF") -> ("Resume", ".PDF")
    so we lowercase the extension before comparing.

    NOTE: this is only the FIRST of three checks. We also check the
    browser-reported content type and, most importantly, the real bytes
    inside the file (see services/pdf_parser.is_pdf_file).
    """
    extension = os.path.splitext(filename)[1].lower()
    return extension in ALLOWED_EXTENSIONS


def build_safe_filename(original_filename):
    """
    Turn whatever the user named their file into something safe to store.

    Two problems we are solving:

    1. SECURITY - a filename like "../../app.py" could make us overwrite
       our own source code. werkzeug's secure_filename() strips slashes,
       dots and any unusual characters.

    2. COLLISIONS - if two students both upload "resume.pdf", the second
       one would replace the first. We add a short random id in front.

    Example:
        "My CV (final).pdf"  ->  "3f9a1c2b7d_My_CV_final.pdf"
    """
    safe_name = secure_filename(original_filename)

    # secure_filename can return an empty string for names made only of
    # strange characters (for example a name written fully in emoji).
    if not safe_name:
        safe_name = "resume.pdf"

    # uuid4() creates a random unique id. We keep the first 10 characters,
    # which is more than enough to avoid collisions in a college project.
    unique_prefix = uuid.uuid4().hex[:10]

    return f"{unique_prefix}_{safe_name}"


def human_readable_size(num_bytes):
    """Turn 248123 into '242 KB' so the UI reads nicely."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def build_chart_data(parsed, ats, job_match, score_history):
    """
    Collect everything the charts need into one plain dictionary.

    Why build it here instead of inside the template?
    Because a Jinja template is for layout, not for reshaping data. Doing
    it in Python keeps the HTML readable and means the numbers can be
    tested without rendering a page.

    The result is handed to the page as JSON inside a
    <script type="application/json"> tag, and static/js/charts.js reads
    it from there. That keeps our data and our code separate - no Python
    values are ever pasted into a JavaScript statement.
    """
    # --- Chart 1: how many skills in each category ---
    # Sorted biggest first, so the bar chart reads top-down.
    skill_pairs = sorted(parsed["skills"]["by_category"].items(),
                         key=lambda item: len(item[1]),
                         reverse=True)

    skills_by_category = {
        "labels": [category for category, _items in skill_pairs],
        "values": [len(items) for _category, items in skill_pairs],
        # The skill names themselves, shown in the tooltip.
        "detail": [", ".join(items) for _category, items in skill_pairs],
    }

    # --- Chart 2: this candidate's score over time ---
    # Only useful with two or more points - one dot is not a trend.
    history = []
    if score_history and len(score_history) >= 2:
        history = [
            {
                "date": row["uploaded_at"].strftime("%d %b %H:%M")
                        if row.get("uploaded_at") else "",
                "score": int(row["ats_score"]),
                "file": row.get("original_name") or "resume.pdf",
            }
            for row in score_history
        ]

    return {
        "atsTotal": ats["total"] if ats else 0,
        "skillsByCategory": skills_by_category,
        "scoreHistory": history,
        "jobMatch": job_match["match_percent"] if job_match else None,
    }


# ---------------------------------------------------------------------
# STEP 3b: Request hooks - run around EVERY request (Phase 9)
# ---------------------------------------------------------------------

@app.before_request
def before_every_request():
    """
    Runs before any route function.

    Two jobs:
      1. Create a fresh CSP nonce for this response.
      2. Reject any POST that does not carry a valid CSRF token.

    Checking CSRF here, centrally, is far safer than remembering to add
    a check to each route. A route added next year is protected
    automatically - security you cannot forget to apply.
    """
    # "g" is Flask's per-request scratch pad. It is emptied automatically
    # when the response is sent, so one request can never see another's.
    g.csp_nonce = secrets.token_urlsafe(16)

    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not security.validate_csrf_token():
            app.logger.warning("CSRF check failed for %s from %s",
                               request.path, request.remote_addr)
            # 400, not 403: from the server's point of view this is a
            # malformed request, and we do not want to hint to an
            # attacker whether the token was missing or merely wrong.
            abort(400, description="csrf")


@app.after_request
def after_every_request(response):
    """Attach the security headers to every response that leaves."""
    nonce = getattr(g, "csp_nonce", "")
    return security.apply_security_headers(response, nonce)


# ---------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------
# app.context_processor makes these available inside EVERY template,
# so index.html can call csrf_token() without app.py passing it in.

@app.context_processor
def inject_security_helpers():
    """Expose csrf_token() and csp_nonce() to all templates."""
    return {
        "csrf_token": security.generate_csrf_token,
        "csp_nonce": lambda: getattr(g, "csp_nonce", ""),
    }


# ---------------------------------------------------------------------
# STEP 4: Routes (URL -> Python function -> HTML page)
# ---------------------------------------------------------------------

@app.route("/")
def home():
    """
    Home page of the website.

    When a visitor opens http://127.0.0.1:5000/ Flask runs this function.
    render_template() finds "templates/index.html", fills in any variables,
    and sends the finished HTML back to the browser.
    """
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
@security.rate_limited
def upload():
    """
    Receive the uploaded resume, validate it, save it, and extract text.

    methods=["POST"] means this URL only accepts form submissions.
    Typing /upload in the address bar sends a GET request and Flask will
    correctly answer "405 Method Not Allowed".

    The validation order below is deliberate - cheapest checks first,
    so we never waste work on an obviously bad request.
    """

    # ---------- Check 1: was a file part sent at all? ----------
    # request.files is a dictionary of uploaded files, keyed by the
    # "name" attribute of the <input> tag: <input name="resume">
    if "resume" not in request.files:
        flash("Please choose a PDF file before clicking Analyze.", "danger")
        return redirect(url_for("home"))

    uploaded_file = request.files["resume"]

    # ---------- Check 2: did the user actually pick something? ----------
    # If the user submits the form with no file, the browser still sends
    # an empty file part whose filename is "".
    if uploaded_file.filename == "":
        flash("No file selected. Please choose your resume in PDF format.",
              "danger")
        return redirect(url_for("home"))

    # ---------- Check 3: is the extension .pdf? ----------
    if not has_allowed_extension(uploaded_file.filename):
        flash("Only PDF files are allowed. Please export your resume as a PDF.",
              "danger")
        return redirect(url_for("home"))

    # ---------- Check 4: does the browser claim it is a PDF? ----------
    # This can be faked, which is exactly why it is not our last check.
    if uploaded_file.mimetype not in ("application/pdf", "application/x-pdf"):
        flash("That file does not look like a PDF. Please upload a real PDF.",
              "danger")
        return redirect(url_for("home"))

    # ---------- Save the file to disk ----------
    stored_filename = build_safe_filename(uploaded_file.filename)
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_filename)

    try:
        uploaded_file.save(save_path)
    except OSError as error:
        # Disk full, folder deleted, no write permission...
        # The real reason goes to the log; the user gets a simple message.
        app.logger.error("Could not save upload: %s", error)
        flash("We could not save your file. Please try again.", "danger")
        return redirect(url_for("home"))

    # ---------- Check 5: is the saved file empty? ----------
    file_size = os.path.getsize(save_path)
    if file_size == 0:
        os.remove(save_path)                    # do not keep junk on disk
        flash("That file is empty (0 bytes). Please upload a valid resume.",
              "danger")
        return redirect(url_for("home"))

    # ---------- Extract the text ----------
    # Each error type from pdf_parser gets its own helpful message.
    try:
        result = extract_text_from_pdf(save_path)

    except EncryptedPDFError as error:
        cleanup_file(save_path)
        flash(str(error), "warning")
        return redirect(url_for("home"))

    except EmptyPDFError as error:
        cleanup_file(save_path)
        flash(str(error), "warning")
        return redirect(url_for("home"))

    except InvalidPDFError as error:
        cleanup_file(save_path)
        flash(str(error), "danger")
        return redirect(url_for("home"))

    except PDFError as error:
        # Safety net for any other error our parser might raise later.
        cleanup_file(save_path)
        app.logger.error("PDF parsing failed: %s", error)
        flash("We could not read that PDF. Please try a different file.",
              "danger")
        return redirect(url_for("home"))

    except Exception as error:
        # Truly unexpected crash. Log the details, show nothing technical.
        cleanup_file(save_path)
        app.logger.exception("Unexpected error while parsing PDF: %s", error)
        flash("Something went wrong while reading your resume. "
              "Please try again.", "danger")
        return redirect(url_for("home"))

    # ---------- Understand the resume (Phase 3) ----------
    # extract_text_from_pdf gave us plain text. parse_resume turns that
    # text into structured information: contact details, sections, skills.
    #
    # This is wrapped in its own try/except because a parsing bug must
    # never take down the whole upload. If it fails we still show the
    # extracted text, which is better than an error page.
    try:
        parsed = parse_resume(result["text"])
    except Exception as error:
        app.logger.exception("Resume parsing failed: %s", error)
        parsed = None
        flash("We read your PDF but could not analyse it fully. "
              "The extracted text is shown below.", "warning")

    # ---------- Calculate the ATS score (Phase 4) ----------
    # Scoring needs the parsed data, so it only runs if parsing worked.
    # It also gets its own try/except: a scoring bug should cost the user
    # the score card, not the entire page.
    ats = None
    if parsed:
        try:
            ats = calculate_ats_score(parsed)
        except Exception as error:
            app.logger.exception("ATS scoring failed: %s", error)
            flash("We analysed your resume but could not calculate the "
                  "ATS score this time.", "warning")

    # ---------- Job description (optional in this phase) ----------
    # .get() with a default means no KeyError if the field is missing.
    # .strip() removes accidental leading/trailing spaces.
    #
    # We also cap the length. A user could paste a whole book into this
    # box; that would cost us money in AI tokens and slow the page down.
    job_description = request.form.get("job_description", "").strip()
    job_description = job_description[:MAX_JOB_DESCRIPTION_CHARS]

    # ---------- Job description matching (Phase 6) ----------
    # Returns None when the user left the job description box empty, and
    # the template then simply skips that whole section.
    job_match = None
    if parsed and job_description:
        try:
            job_match = match_resume_to_job(parsed, job_description,
                                            result["text"])
        except Exception as error:
            app.logger.exception("Job matching failed: %s", error)
            flash("We could not compare your resume with that job "
                  "description.", "warning")

    # ---------- AI analysis (Phase 5) ----------
    # analyze_resume() is written so that it NEVER raises: if there is no
    # API key, or the service is down, it returns rule-based feedback
    # instead. So no try/except is needed around it - but we keep one
    # anyway as a final safety net, because a crash here would lose the
    # ATS score the user has already earned.
    ai = None
    if parsed:
        try:
            ai = analyze_resume(parsed, ats, result["text"], job_description)
        except Exception as error:
            app.logger.exception("AI analysis failed unexpectedly: %s", error)
            ai = None

    if parsed:
        app.logger.info(
            "Parsed '%s' - %d pages, %d words, %d skills, %d/%d sections, "
            "ATS %s",
            stored_filename, result["page_count"], result["word_count"],
            parsed["skills"]["technical_count"],
            parsed["stats"]["sections_present"],
            parsed["stats"]["sections_total"],
            ats["total"] if ats else "n/a",
        )
        if ai:
            app.logger.info("AI feedback source: %s (%s)",
                            ai["source"], ai["provider"])
        if job_match:
            app.logger.info("Job match: %d%% (%d/%d skills)",
                            job_match["match_percent"],
                            job_match["breakdown"]["skills_matched"],
                            job_match["breakdown"]["skills_required"])

    # ---------- Save to MySQL (Phase 7) ----------
    # save_analysis() returns None and logs a warning if the database is
    # switched off or unreachable. It never raises, so the user still
    # sees their results either way.
    analysis_id = None
    if parsed:
        analysis_id = db.save_analysis(
            parsed=parsed,
            ats=ats,
            ai=ai,
            job_match=job_match,
            stored_filename=stored_filename,
            original_filename=uploaded_file.filename,
            extracted_text=result["text"],
            page_count=result["page_count"],
            job_description=job_description,
        )

    # ---------- Housekeeping (Phase 9) ----------
    # Delete resumes older than UPLOAD_RETENTION_HOURS. Doing it here,
    # after a successful upload, means no scheduled task is needed - the
    # folder is tidied by the very traffic that fills it.
    security.cleanup_old_uploads(app.config["UPLOAD_FOLDER"])

    # ---------- Data for the charts (Phase 8) ----------
    # The score history comes from MySQL, so it is empty when the
    # database is switched off. The chart simply does not render then.
    score_history = []
    if parsed and parsed["contact"].get("email"):
        score_history = db.get_user_score_history(
            parsed["contact"]["email"])

    chart_data = None
    if parsed:
        chart_data = build_chart_data(parsed, ats, job_match, score_history)

    # ---------- Show the result ----------
    return render_template(
        "result.html",
        original_name=uploaded_file.filename,
        stored_name=stored_filename,
        file_size=human_readable_size(file_size),
        page_count=result["page_count"],
        word_count=result["word_count"],
        char_count=result["char_count"],
        extracted_text=result["text"],
        job_description=job_description,
        parsed=parsed,
        ats=ats,
        ai=ai,
        job_match=job_match,
        analysis_id=analysis_id,
        chart_data=chart_data,
    )


def cleanup_file(path):
    """
    Delete a file we could not use.

    We call this when parsing fails. There is no reason to keep a resume
    we could not read - it only wastes disk space.

    Deleting must never crash the request, so we catch OSError. But we do
    LOG it: on Windows a silent failure here usually means something is
    still holding the file open, and that is worth knowing about.
    """
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as error:
        app.logger.warning("Could not delete %s: %s", path, error)


@app.route("/history")
def history():
    """
    Show recent analyses saved in MySQL.

    This page exists mainly to prove the database layer works, and it is
    a good thing to demonstrate in a project review: it shows a real
    SELECT with a JOIN across all three tables.

    If the database is switched off we still render the page, with a
    message explaining how to turn it on. Never a crash, never a blank
    screen.
    """
    rows = db.get_recent_analyses(limit=25)
    stats = db.get_statistics()
    distribution = db.get_score_distribution()

    connected, message = db.test_connection()

    return render_template("history.html",
                           rows=rows,
                           stats=stats,
                           distribution=distribution,
                           connected=connected,
                           db_message=message)


@app.route("/health")
def health():
    """
    A tiny 'is the server alive?' endpoint.

    Opening http://127.0.0.1:5000/health should show:
        {"status": "ok"}

    Returning a Python dictionary from a Flask route automatically
    converts it into a JSON response. This is handy for quick testing
    and is also what hosting platforms use to check if an app is running.
    """
    return {"status": "ok", "app": "AI Resume Analyzer", "version": "1.0"}


# ---------------------------------------------------------------------
# STEP 5: Error handlers (friendly pages instead of ugly default errors)
# ---------------------------------------------------------------------

@app.errorhandler(400)
def bad_request(error):
    """
    A malformed request.

    The most common cause here is a failed CSRF check. We show a
    specific, helpful message for that case, because a user whose
    session cookie expired while the page sat open will hit it through
    no fault of their own - and "Bad Request" tells them nothing.

    Notice what we do NOT say: whether the token was missing, wrong or
    expired. Telling an attacker which part of a check failed helps them
    work out how to pass it.
    """
    description = getattr(error, "description", "")

    if description == "csrf":
        message = ("Your session expired while this page was open. "
                   "Please go back to the home page and try again.")
    else:
        message = "We could not understand that request."

    return render_template("error.html", code=400, message=message), 400


@app.errorhandler(403)
def forbidden(error):
    """The request was understood but is not allowed."""
    return render_template("error.html",
                           code=403,
                           message="You do not have access to that page."), 403


@app.errorhandler(404)
def page_not_found(error):
    """Shown when the user opens a URL that does not exist."""
    return render_template("error.html",
                           code=404,
                           message="Page not found."), 404


@app.errorhandler(405)
def method_not_allowed(error):
    """
    Shown when someone types /upload into the address bar.
    /upload only accepts POST (a form submission), not GET.
    """
    return render_template("error.html",
                           code=405,
                           message="That page can only be reached by "
                                   "submitting the upload form."), 405


@app.errorhandler(413)
def file_too_large(error):
    """
    Flask raises 413 automatically when the upload is bigger than
    MAX_CONTENT_LENGTH. We turn it into a friendly message on the
    home page instead of a blank browser error.
    """
    flash(f"That file is too large. The maximum size is "
          f"{MAX_FILE_SIZE_MB} MB.", "danger")
    return redirect(url_for("home"))


@app.errorhandler(429)
def too_many_requests(error):
    """
    The rate limiter rejected this caller.

    security.rate_limited() passes the number of seconds to wait in the
    error description, and we pass it back in the Retry-After header.
    That header is the standard way to tell a well-behaved client
    exactly when to try again, instead of making it guess and hammer us.
    """
    try:
        retry_after = int(getattr(error, "description", "60"))
    except (TypeError, ValueError):
        retry_after = 60

    minutes = max(1, round(retry_after / 60))
    response = render_template(
        "error.html",
        code=429,
        message=(f"You have made too many requests. Please wait about "
                 f"{minutes} minute(s) and try again."))

    return response, 429, {"Retry-After": str(retry_after)}


@app.errorhandler(500)
def internal_error(error):
    """
    Shown when something crashes on the server.

    Notice that we do NOT show the real Python error to the user.
    Leaking internal errors is a security risk. The real error still
    appears in the terminal/logs for the developer.
    """
    return render_template("error.html",
                           code=500,
                           message="Something went wrong on our side. "
                                   "Please try again."), 500


@app.errorhandler(Exception)
def unhandled_exception(error):
    """
    The final safety net: any exception no other handler caught.

    Without this, an unexpected crash would show Flask's own error page.
    In debug mode that page is an interactive Python console - handing a
    stranger the ability to run code on your server.

    We re-raise HTTP errors so the specific handlers above still run,
    log the full traceback for ourselves, and show the user one neutral
    sentence.
    """
    from werkzeug.exceptions import HTTPException

    if isinstance(error, HTTPException):
        return error

    app.logger.exception("Unhandled exception on %s: %s",
                         request.path, error)

    return render_template("error.html",
                           code=500,
                           message="Something went wrong on our side. "
                                   "Please try again."), 500


# ---------------------------------------------------------------------
# STEP 6: Run the development server
# ---------------------------------------------------------------------
# This block runs ONLY when you execute "python app.py" directly.
# FLASK_DEBUG=True in .env turns on auto-reload + detailed console errors.
# Debug mode must always be OFF on a real/public server.
if __name__ == "__main__":
    # ---- Startup housekeeping and safety checks (Phase 9) ----
    # Sweep the uploads folder once at boot, so files left behind by a
    # crash are not kept forever.
    security.cleanup_old_uploads(app.config["UPLOAD_FOLDER"])

    # Print a loud warning for settings that are unsafe outside
    # development. We warn rather than refuse to start, because a
    # student must always be able to run their own project.
    warnings = security.check_production_safety(app)
    if warnings:
        print()
        print("!" * 62)
        print("  SECURITY WARNINGS")
        print("!" * 62)
        for index, warning in enumerate(warnings, start=1):
            print(f"  {index}. {warning}")
        print("!" * 62)
        print()

    debug_mode = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    port = int(os.getenv("PORT", 5000))

    # HOST decides WHO can reach the server.
    #
    #   127.0.0.1  (default) - only this computer. Safest.
    #   0.0.0.0              - every device on your Wi-Fi, so you can open
    #                          the site on your phone for testing.
    #
    # Only switch to 0.0.0.0 on a network you trust (home Wi-Fi), because
    # debug mode exposes a console that can run Python code.
    host = os.getenv("HOST", "127.0.0.1")

    app.run(host=host, port=port, debug=debug_mode)
