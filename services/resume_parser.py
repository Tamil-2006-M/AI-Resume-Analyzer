"""
services/resume_parser.py
=========================
Job of this file: take the clean text produced by pdf_parser.py and
UNDERSTAND it.

It answers four questions:

  1. Who is this person?      -> name, email, phone, LinkedIn, GitHub
  2. What sections exist?     -> Education, Skills, Projects, ...
  3. What skills do they have?-> matched against services/skills_data.py
  4. What is inside each section? -> degrees, projects, certifications

Design rules we follow here
---------------------------
* NEVER invent data. If the phone number is not in the resume, we return
  None instead of guessing. A wrong value is worse than a missing one,
  because the user would believe it.
* No Flask, no database, no file reading. This module only takes a string
  and returns a dictionary, which makes it easy to test:

      python -m services.resume_parser uploads\\some_resume.pdf

Techniques used
---------------
* Regular expressions (regex) for anything with a fixed shape:
  emails, phone numbers, URLs, degrees, CGPA.
* Keyword / dictionary matching for skills and section headings.
  This is the classic, explainable NLP approach - and unlike a machine
  learning model it needs no training data and never hallucinates.
"""

import re

from services.skills_data import (
    TECHNICAL_SKILLS,
    SOFT_SKILLS,
    AMBIGUOUS_SKILLS,
    all_technical_skills,
)


# =====================================================================
# PART 1 - REGULAR EXPRESSIONS
# =====================================================================
# We compile each pattern once, here at the top, instead of inside the
# functions. re.compile() turns the pattern text into a small program;
# doing it once is faster and keeps the patterns together where they are
# easy to read and edit.

# --- Email --------------------------------------------------------
# something@something.something
#   [A-Za-z0-9._%+-]+   one or more letters/digits/dots/underscores
#   @                   a literal @
#   [A-Za-z0-9.-]+      the domain
#   \.[A-Za-z]{2,}      a dot and at least 2 letters (.com, .in, .co.in)
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# --- Phone number -------------------------------------------------
# Handles the formats students actually use:
#   9876543210        +91 9876543210      +91-98765-43210
#   (555) 123-4567    555-123-4567        91 98765 43210
PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?"      # optional country code: +91, 91, +1
    r"(?:\(\d{2,4}\)[\s.-]?)?"     # optional bracketed area code: (555)
    r"\d{3,5}[\s.-]?\d{3,5}"       # the main body, split in 2 groups
    r"(?:[\s.-]?\d{2,4})?"         # optional third group
)

# --- Profile links -------------------------------------------------
LINKEDIN_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/(?:in|pub)/[A-Za-z0-9_%-]+",
    re.IGNORECASE)

GITHUB_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_.-]+",
    re.IGNORECASE)

# A general website / portfolio link that is NOT linkedin or github.
#
# The {3,} is important. Without it this pattern matched "B.Tech" from the
# Education section and reported it as a portfolio website, because "tech"
# is a real domain ending. Requiring at least 3 characters before the dot
# rules out "B.Tech", "M.Tech", "B.Com" and similar abbreviations.
PORTFOLIO_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?[A-Za-z0-9-]{3,}"
    r"\.(?:com|in|dev|io|me|net|org|tech|app)\b"
    r"(?:/[A-Za-z0-9_./-]*)?",
    re.IGNORECASE)

# --- Education ------------------------------------------------------
# \b means "word boundary" so "be" inside "before" is not matched.
DEGREE_PATTERN = re.compile(
    r"\b("
    r"b\.?\s?tech|bachelor(?:'?s)?|b\.?\s?e\.?|b\.?\s?sc|bca|b\.?\s?com|b\.?\s?a\.?|"
    r"m\.?\s?tech|master(?:'?s)?|m\.?\s?e\.?|m\.?\s?sc|mca|mba|m\.?\s?com|"
    r"ph\.?\s?d|doctorate|diploma|"
    r"h\.?s\.?c|s\.?s\.?l\.?c|higher secondary|senior secondary|"
    r"intermediate|12th|10th|xii|x"
    r")\b",
    re.IGNORECASE)

# CGPA 8.4   |  GPA: 3.8  |  Percentage - 82%
GRADE_PATTERN = re.compile(
    r"\b(?:cgpa|gpa|percentage|aggregate|marks|score)\b\s*[:\-]?\s*"
    r"(\d{1,3}(?:\.\d{1,2})?)\s*%?",
    re.IGNORECASE)

# A year between 1950 and 2099
YEAR_PATTERN = re.compile(r"\b(?:19[5-9]\d|20\d{2})\b")

# "3 years of experience", "2+ yrs"
EXPERIENCE_YEARS_PATTERN = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)

# A number used as a result: 40%, 2x, 1500 users, $10,000
QUANTIFIED_PATTERN = re.compile(
    r"(?:\d+(?:[.,]\d+)?\s*%|\b\d+x\b|[$₹]\s?\d|\b\d{3,}\b)",
    re.IGNORECASE)


# =====================================================================
# PART 2 - SECTION DEFINITIONS
# =====================================================================
# Each entry is: (internal key, label shown to the user, [heading aliases])
#
# The aliases are everything a student might actually write as a heading.
# Add more here whenever you find a resume we did not detect correctly.
SECTION_DEFINITIONS = [
    ("summary", "Career Objective / Summary", [
        "objective", "career objective", "professional objective",
        "summary", "professional summary", "career summary", "profile",
        "about me", "about", "profile summary", "personal statement",
    ]),
    ("education", "Education", [
        "education", "educational qualification",
        "educational qualifications", "academic qualification",
        "academic qualifications", "academics", "academic details",
        "academic background", "qualification", "qualifications",
    ]),
    ("skills", "Skills", [
        "skills", "technical skills", "key skills", "core skills",
        "core competencies", "competencies", "technologies",
        "technical expertise", "technical proficiency", "skill set",
        "areas of expertise", "tools and technologies",
        "technologies and tools", "technical skill",
    ]),
    ("projects", "Projects", [
        "projects", "project", "academic projects", "personal projects",
        "project work", "major projects", "mini projects", "key projects",
        "project experience", "notable projects",
    ]),
    ("certifications", "Certifications", [
        "certifications", "certification", "certificates", "certificate",
        "courses", "online courses", "courses and certifications",
        "licenses", "licenses and certifications", "trainings", "training",
        "workshops",
    ]),
    ("experience", "Experience", [
        "experience", "work experience", "professional experience",
        "employment", "employment history", "work history", "internship",
        "internships", "internship experience", "industrial training",
        "career history",
    ]),
    ("achievements", "Achievements", [
        "achievements", "achievement", "awards", "awards and achievements",
        "accomplishments", "honors", "honours", "honors and awards",
        "extra curricular", "extracurricular", "extra-curricular",
        "activities", "co-curricular",
    ]),
]

# Contact information is special: it has no heading. We decide it is
# "present" simply by finding an email or a phone number anywhere.
CONTACT_SECTION = ("contact", "Contact Information")


# =====================================================================
# PART 3 - SMALL HELPERS
# =====================================================================

def _normalize_heading(line):
    """
    Turn a possible heading line into a plain lowercase string.

    "  ***  TECHNICAL SKILLS :  "   ->   "technical skills"

    We strip decorations because resumes use all sorts of separators
    around headings: colons, dashes, pipes, underscores, asterisks.
    """
    text = line.strip()
    # Remove any leading/trailing character that is not a letter or digit.
    text = re.sub(r"^[^A-Za-z0-9]+", "", text)
    text = re.sub(r"[^A-Za-z0-9]+$", "", text)
    # Collapse inner runs of spaces.
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def _looks_like_heading_style(line):
    """
    Does this line LOOK like a heading, ignoring what it says?

    Two styles are accepted, because those are the two real resumes use:
      * ALL CAPS      ->  "TECHNICAL SKILLS"
      * Title Case    ->  "Technical Skills"

    A normal sentence such as "Developed projects using Python" fails
    both tests, because "projects" and "using" start with lowercase.
    """
    words = [w for w in re.findall(r"[A-Za-z]+", line) if len(w) > 2]
    if not words:
        return False

    if line.isupper():
        return True

    # Title Case: every meaningful word starts with a capital letter.
    return all(word[0].isupper() for word in words)


def _match_section_key(line):
    """
    If this line is a section heading, return its key ("skills",
    "education", ...). Otherwise return None.

    The rules, in order:
      1. Headings are short. Anything over 50 characters is a sentence.
      2. Headings do not end with a full stop.
      3. An EXACT match against an alias always wins ("Projects").
      4. Otherwise the line must be short (<= 5 words), look like a
         heading (CAPS or Title Case), and contain an alias
         ("Academic Projects And Internships").
    """
    stripped = line.strip()

    if not stripped or len(stripped) > 50:
        return None
    if stripped.endswith("."):
        return None

    normalized = _normalize_heading(stripped)
    if not normalized:
        return None

    # Rule 3: exact alias match.
    for key, _label, aliases in SECTION_DEFINITIONS:
        if normalized in aliases:
            return key

    # Rule 4: fuzzy match for combined headings.
    word_count = len(normalized.split())
    if word_count > 5 or not _looks_like_heading_style(stripped):
        return None

    for key, _label, aliases in SECTION_DEFINITIONS:
        for alias in aliases:
            # \b...\b makes sure "project" does not match "projected".
            if re.search(r"\b" + re.escape(alias) + r"\b", normalized):
                return key

    return None


def _build_skill_pattern(term):
    """
    Build a regex that matches one skill term safely.

    The problem: a plain search for "java" also matches "JavaScript",
    and a search for "sql" also matches "MySQL".

    The fix: "lookaround" guards. They check what sits either side of the
    match WITHOUT consuming it.

        (?<![A-Za-z0-9+#.])   the character before must NOT be a letter,
                              digit, +, # or .
        (?![A-Za-z0-9+#])     the character after must NOT be one either

    So:
        "java" inside "JavaScript" -> next char is "S" -> rejected
        "sql"  inside "MySQL"      -> previous char is "y" -> rejected
        "c"    inside "C++"        -> next char is "+" -> rejected
        "C, C++"                   -> the standalone C is accepted
    """
    return re.compile(
        r"(?<![A-Za-z0-9+#.])" + re.escape(term) + r"(?![A-Za-z0-9+#])",
        re.IGNORECASE,
    )


# Build every pattern once when the module is first imported, so we do
# not rebuild ~250 regexes on every single upload.
_TECHNICAL_PATTERNS = {
    skill: [_build_skill_pattern(alias) for alias in aliases]
    for skill, aliases in all_technical_skills().items()
}

_SOFT_PATTERNS = {
    skill: [_build_skill_pattern(alias) for alias in aliases]
    for skill, aliases in SOFT_SKILLS.items()
}

# ---------------------------------------------------------------------
# Public names for other modules
# ---------------------------------------------------------------------
# services/job_matcher.py needs exactly the same skill patterns to scan a
# job description. Exposing them here means they are compiled ONCE for
# the whole application instead of twice, and - more importantly - the
# resume and the job description are always matched by identical rules.
# If they used different rules the comparison would be meaningless.
TECHNICAL_SKILL_PATTERNS = _TECHNICAL_PATTERNS
build_skill_pattern = _build_skill_pattern


# =====================================================================
# PART 4 - SECTION DETECTION
# =====================================================================

def detect_sections(text):
    """
    Split the resume into its sections.

    Returns a dictionary:
        {
          "content": {"skills": "Python, Java...", "education": "..."},
          "present": [{"key": ..., "label": ...}, ...],
          "missing": [{"key": ..., "label": ...}, ...],
          "found":   {"skills": True, "experience": False, ...},
          "header":  "the text above the first heading"
        }

    How it works: we walk through the resume line by line. Every time a
    line is recognised as a heading we remember its position. The content
    of a section is everything between its heading and the next heading.
    """
    lines = text.split("\n")

    # Step 1: find the line number of every heading.
    headings = []                      # list of (line_index, section_key)
    for index, line in enumerate(lines):
        key = _match_section_key(line)
        if key:
            headings.append((index, key))

    # Step 2: everything before the first heading is the "header block",
    # which is where the name and contact details normally live.
    first_heading_line = headings[0][0] if headings else min(len(lines), 8)
    header_block = "\n".join(lines[:first_heading_line]).strip()

    # Step 3: collect the text belonging to each heading.
    content = {}
    for position, (line_index, key) in enumerate(headings):
        start = line_index + 1                       # skip the heading itself
        if position + 1 < len(headings):
            end = headings[position + 1][0]          # up to the next heading
        else:
            end = len(lines)                         # ...or the end of the file

        body = "\n".join(lines[start:end]).strip()

        # The same heading can appear twice ("Projects" then "Mini
        # Projects"). Join both blocks instead of losing the first one.
        if key in content:
            content[key] = content[key] + "\n" + body
        else:
            content[key] = body

    # Step 4: decide which sections are present.
    # A section counts as present only if it has a heading AND some text
    # under it. An empty "PROJECTS" heading with nothing below it is not
    # a real section.
    found = {}
    present, missing = [], []

    # Contact is judged by content, not by a heading.
    has_contact = bool(EMAIL_PATTERN.search(text)) or bool(
        _find_phone(text))
    found[CONTACT_SECTION[0]] = has_contact
    (present if has_contact else missing).append(
        {"key": CONTACT_SECTION[0], "label": CONTACT_SECTION[1]})

    for key, label, _aliases in SECTION_DEFINITIONS:
        is_present = key in content and len(content[key].strip()) >= 10
        found[key] = is_present
        (present if is_present else missing).append(
            {"key": key, "label": label})

    return {
        "content": content,
        "present": present,
        "missing": missing,
        "found": found,
        "header": header_block,
    }


# =====================================================================
# PART 5 - CONTACT DETAILS
# =====================================================================

def _find_phone(text):
    """
    Find a phone number and reject look-alikes.

    The regex alone would also match a year range like "2022-2026" or a
    roll number. So after matching we count the digits: a real phone
    number has 10 to 13 of them.
    """
    for match in PHONE_PATTERN.finditer(text):
        candidate = match.group().strip()
        digits = re.sub(r"\D", "", candidate)        # keep digits only

        if 10 <= len(digits) <= 13:
            # Reject a plain 4-digit year that slipped through.
            if len(digits) == 4:
                continue
            return candidate
    return None


def _clean_url(url):
    """Remove a trailing dot/comma and add https:// so links are clickable."""
    url = url.rstrip(".,;)")
    if not url.lower().startswith("http"):
        url = "https://" + url
    return url


def _guess_name(header_block, email):
    """
    Try to work out the candidate's name. Returns None if unsure.

    There is no reliable regex for "a human name", so we use a heuristic:
    look at the first few lines of the resume and pick the first line that
    behaves like a name.

    A line is accepted only if it:
      * has 2 to 4 words                 (Rahul Sharma / Rahul Kumar Sharma)
      * contains only letters, dots, hyphens and apostrophes
      * is not an email, phone, URL or section heading
      * is not a common resume word like "Curriculum Vitae"

    If nothing qualifies we return None rather than guessing. app.py then
    simply shows "Not found", which is honest.
    """
    banned_words = {
        "resume", "curriculum", "vitae", "cv", "profile", "portfolio",
        "objective", "summary", "contact", "address", "phone", "email",
    }

    for line in header_block.split("\n")[:8]:
        candidate = line.strip()

        if not candidate or len(candidate) > 45:
            continue
        # Skip lines that clearly hold contact data instead of a name.
        if "@" in candidate or "http" in candidate.lower():
            continue
        if re.search(r"\d", candidate):
            continue
        if _match_section_key(candidate):
            continue

        words = candidate.split()
        if not (2 <= len(words) <= 4):
            continue
        if any(word.lower().strip(".,") in banned_words for word in words):
            continue
        # Letters, spaces, dots, hyphens and apostrophes only.
        if not re.fullmatch(r"[A-Za-z][A-Za-z.'\- ]+", candidate):
            continue

        return candidate.title() if candidate.isupper() else candidate

    # Last resort: some resumes put the name only in the email address,
    # e.g. rahul.sharma@gmail.com -> "Rahul Sharma".
    if email:
        local_part = email.split("@")[0]
        pieces = re.split(r"[._-]", local_part)
        pieces = [p for p in pieces if p.isalpha() and len(p) > 1]
        if len(pieces) >= 2:
            return " ".join(p.capitalize() for p in pieces[:3])

    return None


def extract_contact_info(text, header_block):
    """
    Pull out every contact detail we can find.

    Any value we cannot find is returned as None - never as a guess.
    """
    email_match = EMAIL_PATTERN.search(text)
    email = email_match.group() if email_match else None

    linkedin_match = LINKEDIN_PATTERN.search(text)
    github_match = GITHUB_PATTERN.search(text)

    # A portfolio is any other website that is not linkedin/github/email.
    portfolio = None
    for match in PORTFOLIO_PATTERN.finditer(text):
        url = match.group()
        lowered = url.lower()

        if "linkedin.com" in lowered or "github.com" in lowered:
            continue
        # Skip the domain part of the email address (gmail.com etc).
        if email and lowered in email.lower():
            continue
        # Skip anything that is really a degree, e.g. "B.Tech".
        if DEGREE_PATTERN.match(url):
            continue

        portfolio = _clean_url(url)
        break

    return {
        "name":      _guess_name(header_block, email),
        "email":     email,
        "phone":     _find_phone(text),
        "linkedin":  _clean_url(linkedin_match.group()) if linkedin_match else None,
        "github":    _clean_url(github_match.group()) if github_match else None,
        "portfolio": portfolio,
    }


# =====================================================================
# PART 6 - SKILL EXTRACTION
# =====================================================================

def extract_skills(text, skills_section_text=""):
    """
    Find every skill from skills_data.py inside the resume.

    Parameters
    ----------
    text : str
        The whole resume. Skills are searched here, because a student may
        mention "Flask" inside a project description without listing it
        under Skills - and that still counts.
    skills_section_text : str
        Just the Skills section. Used for the ambiguous single-letter
        skills (C, R, Go), which are too risky to search for everywhere.

    Returns a dictionary with the skills grouped by category, a flat list,
    and the soft skills.
    """
    found_by_category = {}
    flat_technical = []

    for category, skills in TECHNICAL_SKILLS.items():
        matched_in_category = []

        for skill in skills:
            # Choose WHERE to search based on how risky the name is.
            haystack = skills_section_text if skill in AMBIGUOUS_SKILLS else text
            if not haystack:
                continue

            # any() stops at the first alias that matches - no need to
            # test the rest once we know the skill is present.
            if any(pattern.search(haystack)
                   for pattern in _TECHNICAL_PATTERNS[skill]):
                matched_in_category.append(skill)
                flat_technical.append(skill)

        # Only keep categories that actually matched something, so the
        # dashboard does not show six empty boxes.
        if matched_in_category:
            found_by_category[category] = matched_in_category

    # Soft skills are ordinary words, so we search the whole resume.
    soft_found = [
        skill for skill, patterns in _SOFT_PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    ]

    return {
        "by_category": found_by_category,
        "technical": flat_technical,
        "soft": soft_found,
        "technical_count": len(flat_technical),
        "soft_count": len(soft_found),
    }


# =====================================================================
# PART 7 - SECTION CONTENT EXTRACTION
# =====================================================================

def _split_into_entries(section_text, limit=12):
    """
    Turn a block of section text into a tidy list of lines.

    Removes empty lines, removes the leading bullet character, drops
    fragments that are too short to mean anything, and caps the number of
    items so one strange resume cannot flood the dashboard.
    """
    if not section_text:
        return []

    entries = []
    for line in section_text.split("\n"):
        cleaned = line.strip()
        # pdf_parser already turned •, ●, · into "-", so we strip that.
        cleaned = re.sub(r"^[-*–—]\s*", "", cleaned).strip()

        if len(cleaned) < 4:
            continue
        entries.append(cleaned)

        if len(entries) >= limit:
            break

    return entries


def extract_education(section_text):
    """
    Read the Education section.

    Returns the raw lines plus anything structured we can recognise:
    degrees mentioned, grades (CGPA/percentage) and years.
    """
    entries = _split_into_entries(section_text)

    degrees = []
    for match in DEGREE_PATTERN.finditer(section_text or ""):
        degree = match.group().strip()
        if degree.lower() not in [d.lower() for d in degrees]:
            degrees.append(degree)

    grades = [m.group(1) for m in GRADE_PATTERN.finditer(section_text or "")]
    years = YEAR_PATTERN.findall(section_text or "")

    return {
        "entries": entries,
        "degrees": degrees[:5],
        "grades": grades[:3],
        "years": sorted(set(years))[-4:],      # the most recent few
    }


def extract_projects(section_text):
    """
    Read the Projects section.

    We also count how many project lines contain a NUMBER. Recruiters
    strongly prefer measurable results ("reduced load time by 40%") over
    vague claims ("improved performance"), and Phase 4 uses this count.
    """
    entries = _split_into_entries(section_text, limit=15)

    quantified = [e for e in entries if QUANTIFIED_PATTERN.search(e)]

    return {
        "entries": entries,
        "count": len(entries),
        "quantified_count": len(quantified),
    }


def extract_certifications(section_text):
    """Read the Certifications section."""
    entries = _split_into_entries(section_text, limit=12)
    return {"entries": entries, "count": len(entries)}


def extract_experience(section_text):
    """
    Read the Experience / Internship section.

    Also tries to find a stated number of years ("2 years of experience").
    A fresher usually has none, which is perfectly normal - we return None.
    """
    entries = _split_into_entries(section_text, limit=15)

    years_match = EXPERIENCE_YEARS_PATTERN.search(section_text or "")
    years = int(years_match.group(1)) if years_match else None

    is_internship = bool(
        re.search(r"\bintern(?:ship|ee)?\b", section_text or "",
                  re.IGNORECASE))

    return {
        "entries": entries,
        "count": len(entries),
        "years": years,
        "is_internship": is_internship,
    }


def extract_achievements(section_text):
    """Read the Achievements / Awards section."""
    entries = _split_into_entries(section_text, limit=12)
    return {"entries": entries, "count": len(entries)}


# =====================================================================
# PART 8 - THE MAIN FUNCTION
# =====================================================================

def parse_resume(text):
    """
    Run the whole analysis and return one dictionary.

    This is the only function app.py needs to call. Everything above is
    a building block for it.

    Parameter
    ---------
    text : str
        Clean resume text from services.pdf_parser.extract_text_from_pdf

    Returns
    -------
    dict with keys: contact, sections, skills, education, projects,
                    certifications, experience, achievements, stats
    """
    # Defensive check. parse_resume should never crash the website.
    if not text or not text.strip():
        text = ""

    # --- Step 1: split the resume into sections ---
    sections = detect_sections(text)
    content = sections["content"]

    # --- Step 2: who is this person? ---
    contact = extract_contact_info(text, sections["header"])

    # --- Step 3: what skills do they have? ---
    skills = extract_skills(text, content.get("skills", ""))

    # --- Step 4: read the individual sections ---
    education = extract_education(content.get("education", ""))
    projects = extract_projects(content.get("projects", ""))
    certifications = extract_certifications(content.get("certifications", ""))
    experience = extract_experience(content.get("experience", ""))
    achievements = extract_achievements(content.get("achievements", ""))

    # --- Step 5: a few overall numbers, used by Phase 4 scoring ---
    words = text.split()
    action_verb_count = _count_action_verbs(text)

    stats = {
        "word_count": len(words),
        "char_count": len(text),
        "line_count": len([l for l in text.split("\n") if l.strip()]),
        "bullet_count": len(re.findall(r"^\s*-\s+", text, re.MULTILINE)),
        "action_verb_count": action_verb_count,
        "quantified_count": len(QUANTIFIED_PATTERN.findall(text)),
        "sections_present": len(sections["present"]),
        "sections_total": len(sections["present"]) + len(sections["missing"]),
    }

    return {
        "contact": contact,
        "sections": sections,
        "skills": skills,
        "education": education,
        "projects": projects,
        "certifications": certifications,
        "experience": experience,
        "achievements": achievements,
        "stats": stats,
    }


def _count_action_verbs(text):
    """
    Count how many strong action verbs the resume uses.

    Imported here rather than at the top to keep the skills_data import
    list short and obvious.
    """
    from services.skills_data import ACTION_VERBS

    lowered = text.lower()
    return sum(
        1 for verb in ACTION_VERBS
        if re.search(r"\b" + re.escape(verb) + r"\b", lowered)
    )


# =====================================================================
# Quick manual test
# =====================================================================
# Run:  python -m services.resume_parser uploads\some_resume.pdf
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python -m services.resume_parser <path-to-pdf>")
        sys.exit(1)

    from services.pdf_parser import extract_text_from_pdf, PDFError

    try:
        extracted = extract_text_from_pdf(sys.argv[1])
    except PDFError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    parsed = parse_resume(extracted["text"])

    print("=" * 60)
    print("CONTACT")
    print("=" * 60)
    for field, value in parsed["contact"].items():
        print(f"  {field:10s}: {value if value else '-- not found --'}")

    print("\n" + "=" * 60)
    print("SECTIONS")
    print("=" * 60)
    for section in parsed["sections"]["present"]:
        print(f"  [X] {section['label']}")
    for section in parsed["sections"]["missing"]:
        print(f"  [ ] {section['label']}")

    print("\n" + "=" * 60)
    print(f"TECHNICAL SKILLS ({parsed['skills']['technical_count']})")
    print("=" * 60)
    for category, items in parsed["skills"]["by_category"].items():
        print(f"  {category}: {', '.join(items)}")

    print(f"\nSOFT SKILLS ({parsed['skills']['soft_count']}): "
          f"{', '.join(parsed['skills']['soft']) or '--'}")

    print("\n" + "=" * 60)
    print("STATS")
    print("=" * 60)
    print(json.dumps(parsed["stats"], indent=2))
