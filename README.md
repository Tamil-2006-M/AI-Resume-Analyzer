# AI Resume Analyzer

A web application that reads a PDF resume, analyses it with Python, NLP and an
LLM API, and returns a clear report: an estimated ATS-style score out of 100,
the skills and sections it found, a job-description match percentage, and
specific suggestions for improving the resume.

Built as a college project. Every score is explained, every failure degrades
gracefully, and the whole thing runs without a database or an API key if you
do not have them.

> **Disclaimer.** The ATS score produced here is an **estimated, ATS-style**
> score based on this project's own published rules. It is **not** the score of
> any specific company's applicant tracking system.

---

## Contents

- [Features](#features)
- [Screens](#screens)
- [Tech stack](#tech-stack)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Database setup (optional)](#database-setup-optional)
- [AI setup (optional)](#ai-setup-optional)
- [Running the tests](#running-the-tests)
- [Deployment](#deployment)
- [Project structure](#project-structure)
- [Security](#security)
- [Limitations](#limitations)
- [Documentation](#documentation)

---

## Features

| | Feature | Detail |
| --- | ------- | ------ |
| PDF | **Text extraction** | PyMuPDF, handling scanned, corrupt, encrypted and fake PDFs |
| Parse | **Resume parsing** | Name, email, phone, LinkedIn, GitHub, portfolio - never guessed |
| Sections | **Section detection** | 8 standard sections, recognised across many heading styles |
| Skills | **Skill extraction** | 86 technical skills in 7 categories + 15 soft skills, easily extended |
| Score | **ATS score** | Out of 100 across 8 weighted categories, with the arithmetic shown |
| AI | **AI review** | Strengths, weaknesses, before/after bullet rewrites, suggested summary |
| Match | **Job match** | Match %, matching and missing skills, and what to learn first |
| Charts | **Dashboard** | Chart.js visualisations, each with an accessible table twin |
| History | **Stored history** | Every analysis saved to MySQL, with a score-over-time chart |
| Print | **Save as PDF** | Print stylesheet that strips the navigation |
| Security | **Hardened** | CSRF, CSP with nonces, rate limiting, automatic upload deletion |
| Tests | **158 tests** | No database or API key required to run them |

**It works without MySQL and without an API key.** Both are optional upgrades.
With no database you lose only the History page; with no API key the AI review
falls back to rule-based advice and clearly says so.

---

## Screens

```
  HOME                                  RESULT DASHBOARD
  +------------------------+            +------+------+------+------+
  | Is your resume good    |            | ATS  | JOB  |SKILLS|SECTS |
  | enough to pass the ATS?|            | 84   | 72%  |  30  | 8/8  |
  |                        |            +------+------+------+------+
  | +--------------------+ |            +------------+ +------------+
  | |  Drop your PDF     | |    --->    |   .----.   | | Score      |
  | +--------------------+ |            |  /  84  \  | | Breakdown  |
  | +--------------------+ |            |  \      /  | | ########   |
  | | Job description... | |            |   '----'   | | ######     |
  | +--------------------+ |            |    Good    | | #######    |
  |      [ Analyze ]       |            +------------+ +------------+
  +------------------------+            + AI review, job match, charts
```

---

## Tech stack

| Layer | Technology | Why |
| ----- | ---------- | --- |
| Backend | Python 3.10+, Flask 3.1 | Micro-framework: you can see exactly how a request becomes a response |
| PDF | PyMuPDF 1.28 | Fast, no external binaries, keeps reading order |
| NLP | `re` + dictionary matching | Deterministic and explainable; cannot hallucinate a skill |
| AI | OpenAI / Anthropic / Gemini / Ollama | Swappable by changing one line in `.env` |
| Database | MySQL 8 + `mysql-connector-python` | Transactions, foreign keys, JSON columns |
| Frontend | HTML5, CSS3, JS, Bootstrap 5, Chart.js 4 | No build step - the source is what runs |
| Testing | pytest 8 | 158 tests, runs in under a minute |
| Tools | VS Code, Git, venv | |

---

## How it works

```
   PDF upload
        |
        v
 +------------------+   3 checks: extension, content type, and the
 | Validation       |   %PDF- magic bytes (the only one that cannot be faked)
 +--------+---------+
          v
 +------------------+   services/pdf_parser.py
 | Text extraction  |   PyMuPDF -> cleaned, normalised plain text
 +--------+---------+
          v
 +------------------+   services/resume_parser.py
 | Parsing          |   regex for contacts, keyword matching for skills,
 +--------+---------+   typographic rules for section headings
          v
 +------------------+   services/ats_scorer.py
 | Scoring          |   8 weighted categories -> 0-100, with reasons
 +--------+---------+
          v
 +------------------+------------------+
 | AI review        | Job match        |   ai_analyzer.py / job_matcher.py
 | (LLM, optional)  | (if a JD given)  |   both degrade gracefully
 +--------+---------+------------------+
          v
 +------------------+   database/db.py - one transaction, three tables
 | Save to MySQL    |   (skipped entirely when the database is off)
 +--------+---------+
          v
     Dashboard
```

The split matters: `services/` knows nothing about HTTP, `database/` holds every
line of SQL, and `app.py` only routes. Each module can be run and tested on its
own from the terminal.

---

## Quick start

### Requirements

- Python 3.10 or newer
- Git
- MySQL 8 *(optional)*

### 1. Clone and enter the project

```powershell
git clone https://github.com/YOUR-USERNAME/AI-Resume-Analyzer.git
cd AI-Resume-Analyzer
```

### 2. Create a virtual environment

**Windows (PowerShell)**

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, run this once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**macOS / Linux**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install the dependencies

```powershell
pip install -r requirements.txt
```

### 4. Create your `.env`

```powershell
Copy-Item .env.example .env
```

Then generate a real secret key and paste it into `.env`:

```powershell
python -c "import secrets; print(secrets.token_hex(24))"
```

### 5. Run it

```powershell
python app.py
```

Open <http://127.0.0.1:5000/>.

---

## Configuration

Everything lives in `.env`. Nothing is hardcoded. `.env.example` lists every
variable with comments; `.env` itself is git-ignored.

| Variable | Default | What it does |
| -------- | ------- | ------------ |
| `SECRET_KEY` | - | Signs session cookies. **Set a real one.** |
| `FLASK_DEBUG` | `True` | Auto-reload and detailed errors. **`False` on a server.** |
| `PORT` | `5000` | Port to listen on |
| `HOST` | `127.0.0.1` | `0.0.0.0` also allows phones on your Wi-Fi |
| `AI_PROVIDER` | `openai` | `openai` / `anthropic` / `gemini` / `ollama` |
| `AI_ENABLED` | `true` | `false` forces the rule-based fallback |
| `AI_TIMEOUT` | `45` | Seconds to wait for the AI |
| `DB_ENABLED` | `false` | `true` turns on MySQL history |
| `DB_STORE_RESUME_TEXT` | `true` | `false` keeps resume text out of the database |
| `RATE_LIMIT_MAX` | `12` | Uploads per IP per window; `0` disables |
| `RATE_LIMIT_WINDOW` | `300` | The window, in seconds |
| `UPLOAD_RETENTION_HOURS` | `24` | Auto-delete older uploads; `0` keeps forever |
| `TRUST_PROXY` | `false` | Only `true` behind a proxy you control |

---

## Database setup (optional)

Without this the app works fine; you just do not get the History page.

**1. Start MySQL** (Windows needs an **Administrator** terminal)

```powershell
net start MySQL80
```

**2. Run the setup command**

```powershell
python -m database.db --setup
```

It asks for your MySQL password (hidden as you type), creates the database and
tables from `sql/schema.sql`, and writes the settings into `.env`. Nothing is
written to `.env` if the password is wrong.

**3. Check it**

```powershell
python -m database.db --check
```

<details>
<summary>Loading the schema with the <code>mysql</code> client instead</summary>

`mysql -u root -p < sql/schema.sql` **fails in PowerShell** with
*"The '<' operator is reserved for future use."* - `<` is a bash/cmd operator,
not a PowerShell one. Use one of these:

```powershell
cmd /c "mysql -u root -p < sql\schema.sql"     # hand it to cmd
mysql -u root -p -e "source sql/schema.sql"    # let the client read the file
```

Avoid `Get-Content sql\schema.sql | mysql -u root -p`: stdin is then the pipe,
so the `-p` prompt can swallow the first line of your SQL file.
</details>

### Schema

```
users                    resumes                  analysis_results
------                   -------                  ----------------
id            <-------+  id             <------+  id
name                  +- user_id (FK)          +- resume_id (FK)
email (UNIQUE)           file_name                job_match_score
created_at               extracted_text           skills           (JSON)
                         ats_score                missing_skills   (JSON)
                         page_count               suggestions      (JSON)
                         word_count               sections_missing (JSON)
                         uploaded_at              ai_source
                                                  created_at
```

Plus a `recent_analyses` VIEW joining all three. One resume can have many
analyses - the same PDF compared against different job descriptions.

| Command | What it does |
| ------- | ------------ |
| `python -m database.db --setup` | ask for the password, create tables, save to `.env` |
| `python -m database.db --check` | show settings and test the connection |
| `python -m database.db --init` | run `sql/schema.sql` using settings already in `.env` |

---

## AI setup (optional)

Without a key you still get feedback - it just comes from built-in rules, and
the UI says so with a grey "Rule-based fallback" badge.

Pick a provider by changing one line:

```
AI_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
```

| Provider | Key from | Cost |
| -------- | -------- | ---- |
| `openai` | <https://platform.openai.com/api-keys> | paid, about $0.001 per resume with `gpt-4o-mini` |
| `anthropic` | <https://console.anthropic.com> | paid |
| `gemini` | <https://aistudio.google.com/apikey> | **generous free tier** |
| `ollama` | <https://ollama.com> - runs on your own PC | **free, no key, no internet** |

For a college project, **Gemini** (free tier) or **Ollama** (fully local) are
the practical choices.

**Privacy.** The candidate's email, phone number and profile links are replaced
with `[EMAIL]`, `[PHONE]` and `[LINK]` before any text is sent to the provider.
API keys are sent in headers, never in URLs.

Adding a fifth provider means writing one ~25-line class and adding one line to
the `PROVIDERS` dictionary in `services/ai_analyzer.py`.

---

## Running the tests

```powershell
pytest                          # all 158 tests
pytest -v                       # show every test name
pytest tests/test_security.py   # one file
pytest -k csrf                  # only tests whose name mentions csrf
```

The suite needs **no MySQL and no API key**: `tests/conftest.py` switches both
off before the app is imported and stubs the AI provider. Test PDFs are
generated at runtime rather than committed to Git.

| File | Tests | Covers |
| ---- | ----: | ------ |
| `test_pdf_parser.py` | 20 | extraction, corrupt/locked/scanned PDFs, text cleaning |
| `test_resume_parser.py` | 28 | contact details, sections, skill-matching edge cases |
| `test_ats_scorer.py` | 16 | score bounds, grade bands, discrimination |
| `test_job_matcher.py` | 18 | match %, ambiguous skills, keywords, requirements |
| `test_ai_analyzer.py` | 22 | redaction, JSON parsing, all 7 failure modes |
| `test_security.py` | 24 | CSRF, headers, rate limiting, retention |
| `test_routes.py` | 30 | every route, upload validation, XSS |

Several are **regression tests** for real bugs found during development - a
Windows file lock on corrupt PDFs, an empty resume scoring readability points,
a short job description capping the match at 70%, and a portfolio URL escaping
redaction.

---

## Deployment

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for step-by-step instructions
for Render, PythonAnywhere and a generic Linux server.

The short version:

```bash
gunicorn wsgi:application --workers 2 --timeout 120 --bind 0.0.0.0:$PORT
```

Before deploying, set these in your host's environment settings:

```
FLASK_DEBUG=False
SECRET_KEY=<a fresh random value>
HOST=0.0.0.0
```

> Never run the development server (`python app.py`) on a public address with
> `FLASK_DEBUG=True`. Debug mode exposes an interactive Python console in the
> browser, which is a complete takeover of the machine.

---

## Project structure

```
AI-Resume-Analyzer/
|
+-- app.py                  # Flask app: routes, config, error handlers
+-- security.py             # CSRF, headers, rate limiting, cleanup
+-- wsgi.py                 # entry point for a production server
+-- Procfile                # start command for Render / Railway / Heroku
+-- runtime.txt             # Python version for the host
+-- requirements.txt
+-- pytest.ini
+-- .env                    # real secrets  (NOT committed)
+-- .env.example            # template of every variable
+-- .gitignore
+-- README.md
|
+-- templates/
|   +-- base.html           # shared layout: navbar + footer
|   +-- index.html          # home page + upload form
|   +-- result.html         # the analysis dashboard
|   +-- history.html        # past analyses from MySQL
|   +-- error.html          # 400 / 403 / 404 / 405 / 413 / 429 / 500
|
+-- static/
|   +-- css/style.css       # all styling, including print styles
|   +-- js/script.js        # file validation + UI helpers
|   +-- js/charts.js        # Chart.js dashboard charts
|
+-- services/               # business logic - no HTTP, no SQL
|   +-- pdf_parser.py       # PDF  -> clean text
|   +-- resume_parser.py    # text -> contact, sections, skills
|   +-- ats_scorer.py       # parsed data -> score out of 100
|   +-- ai_analyzer.py      # LLM review (4 swappable providers)
|   +-- job_matcher.py      # resume vs job description -> match %
|   +-- skills_data.py      # the editable skill dictionary
|
+-- database/
|   +-- db.py               # every line of SQL lives here
|
+-- sql/
|   +-- schema.sql          # database + 3 tables + a view
|
+-- tests/                  # 158 automated tests
|   +-- conftest.py         # shared fixtures; builds test PDFs
|   +-- test_*.py           # one file per module
|
+-- docs/
|   +-- DEPLOYMENT.md       # how to put this on the internet
|   +-- INTERVIEW_GUIDE.md  # how to explain this project
|
+-- uploads/                # uploaded PDFs (auto-deleted after 24h)
+-- logs/                   # rotating application log
```

Each service module can be run on its own:

```powershell
python -m services.pdf_parser     "uploads\resume.pdf"
python -m services.resume_parser  "uploads\resume.pdf"
python -m services.ats_scorer     "uploads\resume.pdf"
python -m services.ai_analyzer    "uploads\resume.pdf"
python -m services.job_matcher    "uploads\resume.pdf" "Python Flask SQL"
```

---

## Security

| Protection | How |
| ---------- | --- |
| CSRF | Per-session token in a hidden field, checked on every POST in a `before_request` hook |
| XSS | Jinja auto-escaping plus a CSP with a per-response nonce and **no** `unsafe-inline` for scripts |
| Clickjacking | `X-Frame-Options: DENY` |
| MIME sniffing | `X-Content-Type-Options: nosniff` |
| SQL injection | Parameterised queries everywhere; `LIMIT` forced through `int()` |
| Path traversal | `secure_filename()` plus a UUID prefix |
| Malicious uploads | Extension, content type **and** the `%PDF-` magic bytes |
| Denial of service | 5 MB cap enforced before the body is read, plus per-IP rate limiting |
| Session theft | `HttpOnly`, `SameSite=Lax`, `Secure` outside debug mode |
| Data retention | Uploads older than `UPLOAD_RETENTION_HOURS` are deleted automatically |
| Secret leakage | Credentials only in `.env`; API keys in headers, never URLs |
| Information leakage | Error pages never show a traceback |

`python app.py` prints a loud warning for unsafe settings (debug mode on a
public address, a default `SECRET_KEY`, a well-known database password).

---

## Limitations

Stated honestly, because knowing a system's limits is part of engineering.

- **Two-column PDFs** can interleave text - a limitation of PDF extraction itself.
- **Scanned resumes** cannot be read at all. There is no OCR; the app detects
  this and says so rather than returning nonsense.
- **English only.** Section headings and the skill dictionary are English.
- **Skills outside the dictionary are invisible.** The fix is one line in
  `services/skills_data.py`.
- **Exact keyword matching.** "RDBMS" and "SQL" are different words unless
  aliased. Semantic embeddings would fix this.
- **Depth is not judged.** Listing "AWS" scores the same whether you deployed
  one app or architected a platform.
- **The ATS score is tuned for fresher tech resumes.** An experienced candidate
  with no Certifications section is penalised unfairly.
- **Rate limiting is per-process**, so it resets on restart and is not shared
  between workers. Production would use Redis.
- **No dark mode.** Dark-mode charts need their colours re-stepped and
  re-validated against the dark surface, not simply inverted.
- **No user accounts.** People are identified by the email inside their resume.

---

## Documentation

| Document | For |
| -------- | --- |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Putting the app on the internet |
| [docs/INTERVIEW_GUIDE.md](docs/INTERVIEW_GUIDE.md) | Explaining the project in an interview or viva |

---

## License

MIT - see [LICENSE](LICENSE).
