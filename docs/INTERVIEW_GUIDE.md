# Interview & Viva Guide

How to explain the AI Resume Analyzer to an examiner or an interviewer.

The thing that makes a project memorable is not that it works. It is that you
can say **why** each decision was made, and **what you would do differently**.
This guide is organised around that.

---

## 1. The 30-second pitch

> "I built a web application that analyses PDF resumes. You upload a resume and
> optionally paste a job description, and it returns an ATS-style score out of
> 100, the skills and sections it found, a match percentage against that job,
> and specific suggestions for improving the resume.
>
> It is Flask and Python on the backend, PyMuPDF for PDF extraction, MySQL for
> storage, and an LLM API for the parts that need judgement rather than
> counting. The interesting part is that it works without the database and
> without an API key - both degrade gracefully instead of breaking."

**That last sentence is the one that makes an interviewer look up.** Most
student projects collapse the moment a dependency is missing.

---

## 2. The two-minute walkthrough

Say it as a pipeline:

1. **Upload and validate.** Three checks - the file extension, the content type
   the browser claims, and the first five bytes of the file. Only the last one
   cannot be faked.
2. **Extract.** PyMuPDF turns the PDF into text. Then a cleaning pass fixes
   ligatures, normalises line endings, and collapses whitespace - because those
   quietly break keyword matching later.
3. **Parse.** Regex for anything with a fixed shape (emails, phones, URLs,
   degrees). Dictionary matching for skills. Typographic rules for section
   headings.
4. **Score.** Eight weighted categories adding to 100, each returning the points
   earned *and the reason*, so the user can act on the number.
5. **Review.** The resume goes to an LLM for the parts rules cannot do - judging
   whether a sentence is weak, and rewriting it.
6. **Match.** If a job description was pasted, compare the two and report a
   percentage, the missing skills, and what to learn first.
7. **Store and display.** One MySQL transaction across three tables, then the
   dashboard.

---

## 3. The architecture question

> *"Why did you structure it this way?"*

**Separation of concerns.** Three layers that do not know about each other:

| Layer | Knows about | Does NOT know about |
| ----- | ----------- | ------------------- |
| `app.py` | HTTP, routing, templates | how a PDF works, SQL |
| `services/` | resumes, scoring, the LLM | HTTP, the database |
| `database/db.py` | SQL, transactions | resumes, HTTP |

Three concrete payoffs, and you should name them:

1. **Every service is testable from the terminal** without starting a server:
   `python -m services.ats_scorer resume.pdf`
2. **All SQL is in one file**, so auditing for injection means reading one file.
3. **Swapping MySQL for PostgreSQL** would touch `database/db.py` and nothing
   else.

---

## 4. The questions you will actually be asked

### On PDF handling

**Q: Why PyMuPDF and not PyPDF2?**
Faster, needs no external binary, and it preserves reading order better - which
matters because resumes are full of columns and tables.

**Q: What if the PDF is a scan?**
There is no text to extract, only pixels. We detect it (fewer than 100
characters extracted) and tell the user honestly, rather than returning
nonsense. Adding OCR with Tesseract is the obvious next step.

**Q: Tell me about a bug you hit.**
On Windows, passing a file *path* to PyMuPDF left a file handle open when the
PDF was corrupt, so the app could not delete the bad file. I changed it to read
the bytes myself inside a `with` block and open from memory. There is now a
regression test that copies a corrupt PDF, fails to parse it, and then asserts
the file can be deleted.

### On the NLP

**Q: How do you stop "Java" matching inside "JavaScript"?**
Negative lookahead and lookbehind assertions - they check the characters either
side of a match without consuming them. A plain `\b` word boundary would not
help for `C++` or `.NET`, because `+` and `.` are already non-word characters.

**Q: Why not use spaCy or a trained model?**
Three reasons: it would add a large dependency and a model download for no
benefit here; keyword matching is deterministic, so the same resume always
scores the same; and it **cannot hallucinate a skill the candidate does not
have**. The LLM is used for judgement, which is what it is actually good at.

**Q: How do you tell a heading from a sentence?**
Layered rules: length limit, no trailing full stop, an exact alias match wins,
otherwise it must be five words or fewer *and* be ALL CAPS or Title Case.
`"Developed projects using Python"` fails because "projects" and "using" are
lowercase - typographic style is the signal.

**Q: What happens when you cannot find the name?**
We return `None` and show "Not found". A confident wrong answer is worse than a
known unknown, because the user would believe it.

### On the scoring

**Q: Is this a real ATS score?**
No, and the app says so prominently. It is an estimated, ATS-style score from
our own published rules. Workday, Taleo and Greenhouse all use private
algorithms. What we measure is whether a resume follows the conventions those
systems generally reward.

**Q: Why rule-based rather than machine learning?**
Explainability and data. Every point traces to one line of code, so the user
gets actionable feedback instead of a mystery number. An ML model would need
thousands of labelled resumes I do not have, and could not explain itself.

**Q: What stops a bug producing 112 out of 100?**
Clamping at two levels - per category and on the total. One wrong line in one
scorer degrades one category instead of corrupting the whole result.

### On the AI integration

**Q: How do you switch providers?**
One line in `.env`. Each provider is a class with the same two methods, and the
rest of the code only ever calls `provider.generate()`. That is polymorphism,
and it is the textbook reason object-oriented design exists.

**Q: What if the API is down?**
`analyze_resume()` never raises. It catches timeouts, connection errors, auth
failures, rate limits and malformed replies, and returns rule-based feedback
with an explanation of what happened. There are 22 tests covering exactly this,
including all seven failure modes.

**Q: How do you handle the model returning invalid JSON?**
Layered defence: JSON mode where the provider supports it, prefilling `{` for
Anthropic, stripping markdown fences, falling back to the outermost braces, and
then normalising every field so a wrong type becomes an empty list rather than
a 500 error.

**Q: Any privacy concerns with sending resumes to an API?**
Yes, which is why the email, phone number and profile links are replaced with
placeholders first. The model is judging writing quality; it does not need to
know who the person is. That is data minimisation.

### On the database

**Q: Why is `analysis_results` a separate table from `resumes`?**
One resume can be analysed many times - the same PDF against different job
descriptions. Merging them would duplicate the resume text on every analysis.

**Q: How do you prevent SQL injection?**
Parameterised queries everywhere. The driver sends the query and the data
separately, so data can never be read as SQL. There is one place a value is
interpolated - `LIMIT` - and it is forced through `int()` first, which rejects
anything non-numeric before it reaches MySQL.

**Q: Why one transaction for the three inserts?**
Without it, a crash after the second insert would leave a resume row with no
results attached - corrupt data. `rollback()` on error prevents it. That is the
"A" in ACID: atomicity.

**Q: Why store skills as JSON instead of a separate table?**
Because we only ever read them back as a whole list, so JSON avoids a join. The
honest trade-off: a normalised `skills` table would be far better for analytics
like "how many resumes mention Docker?". I would normalise if the product
needed that.

### On security

**Q: What is CSRF and how did you stop it?**
Another website submits a form to yours using the victim's cookies. We put a
random per-session token in a hidden field and verify it on every POST, in a
`before_request` hook so a route added later is protected automatically.

**Q: Why `secrets.compare_digest` instead of `==`?**
`==` returns as soon as two strings differ, so the comparison time leaks how
much of the token was correct. An attacker can measure that and guess the token
a character at a time. `compare_digest` is constant-time.

**Q: What does your Content-Security-Policy do?**
It is an allow-list the browser enforces. Even if an attacker injected a
`<script>`, the browser would refuse to run it because it lacks this response's
nonce. It is the difference between "we escape our output" and "the browser
will not run it even if we slip up."

**Q: Why is `unsafe-inline` allowed for styles but not scripts?**
We use inline style *attributes* for the score ring, and a nonce cannot apply to
an attribute. An inline style changes how a page looks; an inline script can
steal a session. The blast radius is not comparable.

### On testing

**Q: How do you test the AI without calling it?**
`monkeypatch` replaces `requests.post` with a stub. That lets me test all seven
failure paths deterministically in milliseconds, with no cost and no key. A real
call in a test would be slow, expensive and flaky.

**Q: Unit tests versus integration tests?**
Unit tests check one function with no server - `clean_text("a  b")` returns
`"a b"`. Integration tests go through HTTP and exercise routing, validation,
parsing, scoring and rendering together. You need both: unit tests localise a
bug, integration tests prove the pieces fit.

---

## 5. The three best things to volunteer

Interviewers remember candidates who bring up their own engineering reasoning.

**1. Graceful degradation is designed in, not bolted on.**
No database? The analysis still runs; you lose only the History page. No API
key? Rule-based advice, and the UI says so. API down? Same. It is tested: 22
tests for the AI fallback alone.

**2. Every number is explainable.**
Each scoring category returns the points, *the reason*, and *the fix*. The user
can expand "How these points were calculated" and check the arithmetic. A score
with no explanation is useless.

**3. I chose the safe failure, deliberately.**
Single-letter skills like `C`, `R` and `Go` are only matched inside a skills
list, because a job advert saying "ready to go the extra mile" would otherwise
report Go as a required language. That trades a rare false negative for near-zero
false positives - the right trade when the user will act on the output.

---

## 6. Bugs you found - and why they are worth mentioning

Naming a bug you found *yourself* signals that you actually built the thing.

| Bug | Why it happened | The fix |
| --- | --------------- | ------- |
| The app hung in an infinite loop at startup | A Jinja tag written inside an HTML comment - Jinja runs tags before the browser ever sees the comment, so `base.html` extended itself | Never put `{% %}` inside `<!-- -->` |
| Corrupt uploads could not be deleted on Windows | PyMuPDF held a file handle after a failed open | Read the bytes and open from memory instead of from a path |
| An empty resume scored 4/100 | It earned readability points for "lines are easy to scan" - because it had no long lines | Guard: under 50 words, readability scores zero |
| A perfect match was capped at 70% | Short job descriptions yield almost no keywords, so the keyword half of the formula had nothing to score | Below 5 keywords, score on skill coverage alone and say so |
| A portfolio URL leaked to the AI | The redaction pattern required a `/path`, so a bare `name.dev` slipped through | Match bare domains too, with a 3-character minimum so `B.Tech` is not caught |
| The print button would have been blocked | `onclick=""` is an inline script, and our own CSP forbids those | Moved the handler into `script.js` |

---

## 7. "What would you do differently?"

Have a real answer ready. Saying "nothing" sounds like you did not think about
it.

- **Semantic matching instead of exact keywords.** Sentence embeddings would
  recognise that "RDBMS" and "SQL" are the same idea. That is the single
  biggest quality improvement available.
- **Add OCR.** Tesseract would let the app read scanned resumes, which it
  currently rejects.
- **Background jobs.** The AI call blocks the request for 5-15 seconds. Celery
  or RQ with a progress bar would be the right shape.
- **Redis for rate limiting.** The current counters live in one process's
  memory, so they reset on restart and are not shared between workers.
- **Real user accounts.** Identifying people by the email inside their resume
  is a workaround, not a design.
- **Normalise the skills tables**, if the product ever needed analytics across
  resumes.

---

## 8. For your resume

Pick one. The first is the strongest.

**Detailed (two lines):**

> **AI Resume Analyzer** - Python, Flask, MySQL, PyMuPDF, LLM API, Chart.js
> Built a full-stack web app that parses PDF resumes and returns an explainable
> ATS-style score across 8 weighted categories, a job-description match
> percentage, and AI-generated rewrite suggestions. Designed the LLM layer to be
> provider-agnostic across 4 APIs with a rule-based fallback, so the app stays
> fully functional with no API key or database. Hardened with CSRF protection, a
> nonce-based CSP and rate limiting; covered by 158 automated tests.

**Concise (one line):**

> **AI Resume Analyzer** (Python, Flask, MySQL, LLM API) - Full-stack resume
> analysis tool producing an explainable ATS score, job-match percentage and
> AI rewrite suggestions; provider-agnostic AI layer with graceful fallback,
> 158 automated tests. [github.com/you/AI-Resume-Analyzer]

**What makes these work:**

- **Numbers.** "8 weighted categories", "4 APIs", "158 tests" - specifics beat
  adjectives.
- **The word "explainable".** It says you thought about the user.
- **"Graceful fallback".** Engineering maturity in two words.
- **A link.** Always include the repository, and the live URL if deployed.

Avoid: "Developed a website using Python and Flask." That describes a tutorial.

---

## 9. Demo checklist

Before you present, rehearse this order:

1. **Show the home page.** Point out the disclaimer - you are being honest about
   what the score means.
2. **Upload a good resume.** Talk through the summary bar while it loads.
3. **Expand "How these points were calculated"** on one category. This is the
   moment that separates your project from a black box.
4. **Paste a job description and re-upload.** Show the match percentage and the
   "learn these first" list.
5. **Upload a `.txt` renamed to `.pdf`.** Show that it is rejected, and explain
   the magic-bytes check.
6. **Open the History page.** Show the data really is in MySQL.
7. **Run `pytest`** in a terminal. 158 passing tests is a strong closing image.

Have a backup: a screen recording, in case the Wi-Fi fails or a free host is
asleep.

**If something breaks live, do not panic - narrate it.** "That is the rate
limiter doing its job" or "the free host went to sleep, it takes 30 seconds to
wake" turns a failure into evidence that you understand your own system.
