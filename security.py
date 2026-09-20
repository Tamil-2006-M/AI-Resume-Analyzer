"""
security.py
===========
Job of this file: the defensive layer that sits around every request.

It is a top-level module rather than one of the services/ files because
it is not business logic. services/ answers "what does this resume say?";
this file answers "is this request safe to serve?".

What it provides
----------------
1. CSRF protection            - stops another website submitting our form
2. Security response headers  - tells the browser how to behave
3. A Content-Security-Policy  - blocks injected scripts
4. Rate limiting              - stops one person flooding the server
5. Upload retention           - deletes old resumes automatically
6. A production sanity check  - refuses obviously unsafe settings

Everything here is written by hand with the standard library. We could
have installed Flask-WTF and Flask-Limiter, but two of the project's own
rules are "avoid unnecessary libraries" and "be able to explain every
line". Each protection below is about twenty lines, and you can describe
exactly what it does.
"""

import os
import time
import secrets
import logging
from functools import wraps
from collections import defaultdict

from flask import session, request, abort, render_template

logger = logging.getLogger(__name__)


def _env(name, default=""):
    """Read an environment variable, trimming spaces and stray quotes."""
    return os.getenv(name, default).strip().strip('"').strip("'")


def _env_int(name, default):
    """Read an environment variable that should be a whole number."""
    try:
        return int(_env(name, str(default)) or default)
    except ValueError:
        logger.warning("%s is not a number, using %s", name, default)
        return default


# =====================================================================
# PART 1 - CSRF PROTECTION
# =====================================================================
#
# What is CSRF (Cross-Site Request Forgery)?
# -----------------------------------------
# Imagine you are logged into our site. You then visit evil.com, which
# quietly contains:
#
#     <form action="http://our-site/upload" method="POST"
#           enctype="multipart/form-data" id="f"> ... </form>
#     <script>document.getElementById("f").submit()</script>
#
# Your browser happily sends the request WITH your cookies, because that
# is what browsers do. The server sees a normal, logged-in request.
#
# The fix: put a secret random token in the user's session AND in a
# hidden field of our own form. evil.com cannot read our session, so it
# cannot guess the token, so its forged form is rejected.
#
# Two details that matter:
#   * The token lives in the session cookie, which is signed with
#     SECRET_KEY, so it cannot be forged.
#   * We compare with secrets.compare_digest(), not "==", to avoid a
#     timing attack (see the comment on that line).

CSRF_SESSION_KEY = "_csrf_token"
CSRF_FIELD_NAME = "csrf_token"


def generate_csrf_token():
    """
    Return this visitor's CSRF token, creating one on first use.

    The same token is reused for the whole session. That is standard and
    safe - the token is a secret, not a one-time password.
    """
    if CSRF_SESSION_KEY not in session:
        session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
    return session[CSRF_SESSION_KEY]


def validate_csrf_token():
    """
    Check the token the form sent against the one in the session.

    Returns True if they match.
    """
    expected = session.get(CSRF_SESSION_KEY)
    if not expected:
        return False

    # The token can arrive in the form body or in a header (for fetch()).
    submitted = (request.form.get(CSRF_FIELD_NAME)
                 or request.headers.get("X-CSRF-Token", ""))
    if not submitted:
        return False

    # compare_digest takes the same amount of time whether the strings
    # differ at character 1 or character 30. A plain "==" returns early
    # on the first mismatch, and an attacker can measure that difference
    # to guess the token one character at a time. This is a "timing
    # attack", and compare_digest is the standard defence.
    return secrets.compare_digest(str(expected), str(submitted))


# =====================================================================
# PART 2 - RATE LIMITING
# =====================================================================
#
# Why: parsing a PDF and calling an AI API costs real CPU time and real
# money. Without a limit, one script could submit a thousand uploads a
# minute and either run up an API bill or take the site down.
#
# How: a "sliding window". For each IP address we keep the timestamps of
# its recent requests. Before serving a new one we throw away timestamps
# older than the window and count what is left.
#
# HONEST LIMITATION - say this in your viva before anyone asks:
# this counter lives in the memory of one Python process. It resets when
# the app restarts, and with several worker processes each keeps its own
# count. It is right for a college project and a single server. A real
# deployment stores the counters in Redis so every worker shares them.

_request_log = defaultdict(list)

# When the dictionary grows past this many addresses we clear out the
# stale ones. Without this, a long-running server would slowly leak
# memory as one entry per visiting IP accumulates forever.
_CLEANUP_THRESHOLD = 1000


def _client_ip():
    """
    Work out who is calling.

    Behind a proxy (nginx, Render, Heroku) the real address is in the
    X-Forwarded-For header, and request.remote_addr is just the proxy.

    SECURITY NOTE: a client can send X-Forwarded-For itself, so this is
    only trustworthy when you KNOW you are behind a proxy you control.
    That is why it is opt-in with TRUST_PROXY, default off.
    """
    if _env("TRUST_PROXY", "false").lower() in ("true", "1", "yes"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            # The header is a list: "client, proxy1, proxy2".
            # The first entry is the original client.
            return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _prune(now, window):
    """Drop addresses that have not been seen inside the window."""
    for ip in list(_request_log.keys()):
        _request_log[ip] = [t for t in _request_log[ip] if now - t < window]
        if not _request_log[ip]:
            del _request_log[ip]


def check_rate_limit(max_requests=None, window_seconds=None):
    """
    Return (allowed, seconds_to_wait) for the current caller.

    allowed is False when this IP has already used up its quota.
    """
    max_requests = max_requests or _env_int("RATE_LIMIT_MAX", 12)
    window_seconds = window_seconds or _env_int("RATE_LIMIT_WINDOW", 300)

    # Setting the limit to 0 turns rate limiting off entirely, which is
    # handy while developing.
    if max_requests <= 0:
        return True, 0

    now = time.time()
    ip = _client_ip()

    if len(_request_log) > _CLEANUP_THRESHOLD:
        _prune(now, window_seconds)

    # Keep only this IP's requests that are still inside the window.
    recent = [t for t in _request_log[ip] if now - t < window_seconds]
    _request_log[ip] = recent

    if len(recent) >= max_requests:
        # Tell the caller when the oldest request will expire.
        retry_after = int(window_seconds - (now - recent[0])) + 1
        logger.warning("Rate limit hit by %s (%d requests in %ds)",
                       ip, len(recent), window_seconds)
        return False, max(retry_after, 1)

    recent.append(now)
    return True, 0


def rate_limited(view_function):
    """
    A decorator that applies the rate limit to one route.

    Used as:

        @app.route("/upload", methods=["POST"])
        @rate_limited
        def upload():
            ...

    @wraps copies the original function's name across. Without it every
    decorated view would be called "wrapper", and Flask - which keys its
    URL map by function name - would refuse to start with a duplicate
    endpoint error.
    """
    @wraps(view_function)
    def wrapper(*args, **kwargs):
        allowed, retry_after = check_rate_limit()
        if not allowed:
            # 429 is the HTTP status for "Too Many Requests".
            abort(429, description=str(retry_after))
        return view_function(*args, **kwargs)
    return wrapper


def reset_rate_limits():
    """Clear the counters. Used by the test suite between tests."""
    _request_log.clear()


# =====================================================================
# PART 3 - SECURITY HEADERS
# =====================================================================

def build_csp(nonce):
    """
    Build the Content-Security-Policy header.

    CSP is the browser's own allow-list. Even if an attacker managed to
    inject a <script> tag into one of our pages, the browser would refuse
    to run it because it does not carry tonight's nonce.

    A "nonce" is a random value generated fresh for every single
    response. Our own inline scripts get nonce="..."; injected ones
    cannot, because the attacker does not know the value.

    Each directive, in plain English:
      default-src 'self'   only load things from our own site
      script-src           our site, the jsDelivr CDN, and tagged inline
      style-src            ...plus inline styles (see the note below)
      img-src              our site, data: URIs, and https images
      font-src             our site and the CDN (Bootstrap Icons)
      connect-src 'self'   fetch/XHR may only call us back
      frame-ancestors      nobody may put our site in an iframe
      form-action 'self'   our forms may only submit to us
      base-uri 'self'      stops an injected <base> tag hijacking links
      object-src 'none'    no Flash/Java applets, ever

    Why 'unsafe-inline' for styles but not for scripts?
    Because we use inline style attributes (style="--value: 78") for the
    score ring, and a nonce cannot apply to an ATTRIBUTE - only to a
    <style> tag. An inline style can change how a page looks; an inline
    script can steal a session. The risk is not comparable, so allowing
    one and blocking the other is the normal trade-off.
    """
    cdn = "https://cdn.jsdelivr.net"
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' {cdn} 'nonce-{nonce}'",
        f"style-src 'self' {cdn} 'unsafe-inline'",
        "img-src 'self' data: https:",
        f"font-src 'self' {cdn}",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
    ])


def apply_security_headers(response, nonce):
    """
    Add the standard protective headers to every response.

    What each one does:

    Content-Security-Policy
        The allow-list described above. The single most effective
        defence against cross-site scripting.

    X-Content-Type-Options: nosniff
        Stops the browser "guessing" a file's type. Without it, a file
        we serve as text could be run as JavaScript if the browser
        decided it looked like a script.

    X-Frame-Options: DENY
        Nobody can load our site inside an <iframe>. This blocks
        "clickjacking", where an attacker puts an invisible copy of our
        page over their own buttons so your clicks land on ours.

    Referrer-Policy
        Controls what we leak in the Referer header when a user clicks
        a link out. strict-origin-when-cross-origin sends the full URL
        within our site, but only the bare domain to other sites - so a
        result page URL never leaks to a third party.

    Permissions-Policy
        Turns off browser features we never use. A resume analyser has
        no business asking for the camera, microphone or location, so we
        give up the right to ask.
    """
    response.headers["Content-Security-Policy"] = build_csp(nonce)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()")

    # HSTS tells the browser "only ever reach me over HTTPS". It must
    # ONLY be sent over a real HTTPS connection - sending it from a
    # local http:// dev server would lock the browser out of
    # http://localhost for months, with no easy way back.
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = \
            "max-age=31536000; includeSubDomains"

    return response


# =====================================================================
# PART 4 - UPLOAD RETENTION
# =====================================================================

def cleanup_old_uploads(folder, max_age_hours=None):
    """
    Delete uploaded resumes older than the retention period.

    Two reasons this matters:

    PRIVACY - a resume contains someone's name, phone number and address.
    Keeping it forever, on a student project server, for no reason, is
    exactly the habit that causes data breaches. Storing personal data
    only as long as you need it is a legal requirement in many places.

    DISK    - 5 MB per upload fills a small server surprisingly fast.

    Set UPLOAD_RETENTION_HOURS=0 in .env to keep files forever.
    Returns the number of files deleted.
    """
    if max_age_hours is None:
        max_age_hours = _env_int("UPLOAD_RETENTION_HOURS", 24)

    if max_age_hours <= 0 or not os.path.isdir(folder):
        return 0

    cutoff = time.time() - (max_age_hours * 3600)
    deleted = 0

    for filename in os.listdir(folder):
        # Never touch .gitkeep or anything that is not an upload.
        if not filename.lower().endswith(".pdf"):
            continue

        path = os.path.join(folder, filename)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                deleted += 1
        except OSError as error:
            # One locked file must not stop the rest being cleaned.
            logger.warning("Could not delete old upload %s: %s",
                           filename, error)

    if deleted:
        logger.info("Deleted %d upload(s) older than %d hour(s)",
                    deleted, max_age_hours)
    return deleted


# =====================================================================
# PART 5 - PRODUCTION SANITY CHECK
# =====================================================================

def check_production_safety(app):
    """
    Warn loudly about settings that are dangerous outside development.

    Returns a list of problems found. Nothing here stops the app - a
    student needs to be able to run it - but the warnings are printed in
    red-flag language so they are hard to ignore.
    """
    problems = []

    debug_on = _env("FLASK_DEBUG", "True").lower() == "true"
    host = _env("HOST", "127.0.0.1")
    secret = app.config.get("SECRET_KEY", "")

    # Debug mode exposes an interactive console that can execute
    # arbitrary Python from the browser. On a public address that is a
    # complete takeover of the machine.
    if debug_on and host == "0.0.0.0":
        problems.append(
            "FLASK_DEBUG=True together with HOST=0.0.0.0 exposes a Python "
            "console to your whole network. Set FLASK_DEBUG=False before "
            "sharing this app.")

    if secret in ("", "dev-secret-change-me"):
        problems.append(
            "SECRET_KEY is missing or still the default. Session cookies "
            "can be forged. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(24))"')

    if _env("DB_PASSWORD", "") in ("root", "password", "admin", "123456"):
        problems.append(
            "DB_PASSWORD is a well-known default. Fine on localhost, "
            "never on a real server.")

    for problem in problems:
        logger.warning("SECURITY: %s", problem)

    return problems
