"""
services/job_matcher.py
=======================
Job of this file: compare the resume against a job description (JD) and
say how well they match.

The user pastes something like:

    "Looking for a Python developer with Flask, SQL, REST API, Git
     and AWS knowledge. 2+ years experience preferred."

and we answer:

    Job Match: 72%
    Matching : Python, SQL, Git
    Missing  : Flask, REST API, AWS

Why this matters
----------------
An ATS does not score a resume in the abstract. It scores it AGAINST one
specific job. The same resume can be excellent for a backend role and
poor for a data science role. This module is what turns a general score
into advice for one particular application.

How the percentage is calculated
--------------------------------
    Skill coverage    70%   how many of the JD's skills you have
    Keyword coverage  30%   how many of the JD's important words appear

Skills are weighted much higher because a named technology ("Flask") is
a hard requirement, whereas a keyword ("scalable") is softer language.

The same regex patterns used on the resume are reused here. That is
deliberate: if the resume and the JD were scanned by different rules,
comparing them would be meaningless.
"""

import re
from collections import Counter

from services.skills_data import TECHNICAL_SKILLS, AMBIGUOUS_SKILLS
from services.resume_parser import TECHNICAL_SKILL_PATTERNS


# =====================================================================
# PART 1 - STOP WORDS
# =====================================================================
# "Stop words" are words too common to be meaningful. If we did not
# remove them, the top keywords of every job description would be
# "the", "and", "with" - useless for matching.
#
# The second group is job-advert boilerplate: words that appear in every
# posting regardless of the role.
STOP_WORDS = {
    # ---- ordinary English ----
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but",
    "by", "can", "could", "did", "do", "does", "for", "from", "had",
    "has", "have", "he", "her", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "may", "might", "must", "of", "on", "or", "our",
    "shall", "she", "should", "so", "such", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those",
    "to", "up", "us", "was", "we", "were", "what", "when", "where",
    "which", "while", "who", "will", "with", "would", "you", "your",
    "all", "any", "both", "each", "more", "most", "other", "some",
    "very", "too", "also", "not", "no", "only", "own", "same", "just",
    "about", "after", "before", "between", "during", "over", "under",
    "again", "further", "once", "here", "why", "out", "off", "down",
    "above", "below", "through", "because", "until", "against",

    # ---- job-advert boilerplate ----
    "job", "jobs", "role", "roles", "position", "positions", "candidate",
    "candidates", "applicant", "applicants", "company", "companies",
    "team", "teams", "work", "working", "works", "looking", "seeking",
    "required", "requirement", "requirements", "preferred", "must",
    "responsibility", "responsibilities", "qualification",
    "qualifications", "skill", "skills", "ability", "abilities",
    "experience", "experienced", "knowledge", "good", "strong",
    "excellent", "years", "year", "plus", "etc", "including", "include",
    "includes", "well", "able", "new", "high", "low", "using", "use",
    "used", "help", "join", "apply", "please", "send", "email", "salary",
    "benefits", "location", "remote", "hybrid", "office", "full", "time",
    "part", "opportunity", "opportunities", "environment", "culture",
    "great", "best", "top", "one", "two", "three", "day", "days", "week",
    "month", "months", "per", "and/or", "you'll", "we're",
}

# Words shorter than this are ignored. "AI" and "ML" are real keywords
# but they are already handled as SKILLS, so we lose nothing.
MIN_KEYWORD_LENGTH = 3

# How many JD keywords we compare against. Beyond roughly 20 the words
# stop being distinctive.
MAX_KEYWORDS = 20

# Below this many keywords, the keyword score is not trustworthy.
#
# Why this exists: a short posting like "Need Python, Flask, SQL and Git"
# produces almost no keywords once skills and stop words are removed. A
# candidate matching ALL FOUR skills was still capped at 70%, because the
# keyword half of the formula had nothing to score. That is clearly wrong,
# so with too few keywords we score on skills alone and say so.
MIN_KEYWORDS_FOR_WEIGHTING = 5


# =====================================================================
# PART 2 - READING SKILLS OUT OF THE JOB DESCRIPTION
# =====================================================================

def _line_looks_like_a_skill_list(line):
    """
    Decide whether a line is a list of technologies rather than prose.

    Used only for the risky single-letter skills (C, R, Go). In a resume
    we solved this by looking only inside the Skills section, but a job
    description has no sections - it is one block of prose.

    A job advert often contains "ready to go the extra mile", and a naive
    search would report "Go" as a required programming language.

    So for those skills we require the line to look like a list:
      * it contains at least two commas or slashes, OR
      * it already contains two other recognised technologies.
    """
    separators = line.count(",") + line.count("/") + line.count("|")
    if separators >= 2:
        return True

    # Count how many normal (non-ambiguous) skills appear on this line.
    hits = 0
    for skill, patterns in TECHNICAL_SKILL_PATTERNS.items():
        if skill in AMBIGUOUS_SKILLS:
            continue
        if any(pattern.search(line) for pattern in patterns):
            hits += 1
            if hits >= 2:
                return True
    return False


def extract_job_skills(job_description):
    """
    Find every technical skill the job description asks for.

    Returns
    -------
    dict:
        skills      : flat list of skill names, most-mentioned first
        by_category : {"Databases": ["MySQL"], ...}
        counts      : {"Python": 3} - how often each was mentioned
    """
    if not job_description:
        return {"skills": [], "by_category": {}, "counts": {}}

    lines = job_description.split("\n")
    counts = Counter()

    for category, skills in TECHNICAL_SKILLS.items():
        for skill in skills:
            patterns = TECHNICAL_SKILL_PATTERNS[skill]

            if skill in AMBIGUOUS_SKILLS:
                # Risky name: only accept it on a list-like line.
                total = 0
                for line in lines:
                    if not _line_looks_like_a_skill_list(line):
                        continue
                    total += sum(len(p.findall(line)) for p in patterns)
                if total:
                    counts[skill] = total
            else:
                # Safe name: search the whole job description.
                total = sum(len(p.findall(job_description))
                            for p in patterns)
                if total:
                    counts[skill] = total

    # Sort so the most-repeated (= most important) skills come first.
    ordered = [skill for skill, _count in counts.most_common()]

    by_category = {}
    for category, skills in TECHNICAL_SKILLS.items():
        found = [s for s in ordered if s in skills]
        if found:
            by_category[category] = found

    return {
        "skills": ordered,
        "by_category": by_category,
        "counts": dict(counts),
    }


# =====================================================================
# PART 3 - READING KEYWORDS OUT OF THE JOB DESCRIPTION
# =====================================================================

def extract_job_keywords(job_description, known_skills):
    """
    Find the important non-skill words in the job description.

    Why bother, when we already extract skills?
    Because a JD contains meaningful words that are not technologies:
    "microservices", "scalable", "debugging", "deployment", "agile".
    An ATS matches on these too, and they are worth mirroring in a
    resume - honestly, where they apply.

    Method (classic, explainable NLP):
        1. lowercase and split into words
        2. drop stop words and very short words
        3. drop anything that is already counted as a skill
        4. count what is left and keep the most frequent

    Returns a list of (word, count) pairs, most frequent first.
    """
    if not job_description:
        return []

    # Everything a skill name covers, so we do not count it twice.
    skill_words = set()
    for skill in known_skills:
        for part in re.split(r"[^A-Za-z0-9]+", skill.lower()):
            if part:
                skill_words.add(part)

    words = re.findall(r"[A-Za-z][A-Za-z+#.-]{1,}", job_description.lower())

    counts = Counter()
    for word in words:
        cleaned = word.strip(".-")
        if len(cleaned) < MIN_KEYWORD_LENGTH:
            continue
        if cleaned in STOP_WORDS or cleaned in skill_words:
            continue
        if cleaned.isdigit():
            continue
        counts[cleaned] += 1

    return counts.most_common(MAX_KEYWORDS)


# =====================================================================
# PART 4 - JOB REQUIREMENTS (experience, education)
# =====================================================================

EXPERIENCE_PATTERN = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)", re.IGNORECASE)

DEGREE_PATTERN = re.compile(
    r"\b(b\.?\s?tech|b\.?\s?e\.?|b\.?\s?sc|bca|bachelor(?:'?s)?|"
    r"m\.?\s?tech|m\.?\s?sc|mca|master(?:'?s)?|mba|ph\.?\s?d)\b",
    re.IGNORECASE)


def extract_job_requirements(job_description):
    """
    Pull out the hard filters a recruiter screens on first.

    Returns years of experience asked for (or None) and any degree named.
    """
    if not job_description:
        return {"years": None, "degrees": [], "is_fresher_friendly": True}

    years_match = EXPERIENCE_PATTERN.search(job_description)
    years = int(years_match.group(1)) if years_match else None

    degrees = []
    for match in DEGREE_PATTERN.finditer(job_description):
        degree = match.group().strip()
        if degree.lower() not in [d.lower() for d in degrees]:
            degrees.append(degree)

    # A role asking for 0-1 years, or not mentioning years at all, is
    # realistic for a fresher.
    fresher_friendly = years is None or years <= 1

    return {
        "years": years,
        "degrees": degrees[:3],
        "is_fresher_friendly": fresher_friendly,
    }


# =====================================================================
# PART 5 - GRADING
# =====================================================================

def get_match_grade(percent):
    """Turn the percentage into a label, a colour and a sentence."""
    if percent >= 80:
        return ("Excellent Match", "success",
                "You meet almost every requirement. Apply with confidence.")
    if percent >= 60:
        return ("Good Match", "success",
                "You are a realistic candidate. Add the missing skills "
                "below to strengthen the application.")
    if percent >= 40:
        return ("Partial Match", "warning",
                "You meet some requirements. Tailor your resume to this "
                "job before applying.")
    return ("Weak Match", "danger",
            "This role asks for skills your resume does not show. "
            "Either learn them or target a closer role.")


# =====================================================================
# PART 6 - THE MAIN FUNCTION
# =====================================================================

def match_resume_to_job(parsed, job_description, resume_text=""):
    """
    Compare a parsed resume against a job description.

    Parameters
    ----------
    parsed          : output of resume_parser.parse_resume()
    job_description : the raw text the user pasted
    resume_text     : the full resume text, used for keyword matching

    Returns
    -------
    dict - or None if no job description was given, so the template can
           simply skip the whole section.
    """
    # Nothing to compare against.
    if not job_description or not job_description.strip():
        return None

    job_description = job_description.strip()
    resume_text = resume_text or ""
    resume_lower = resume_text.lower()

    resume_skills = set(parsed["skills"]["technical"])

    # ---------- Step 1: what does the job ask for? ----------
    job_skill_data = extract_job_skills(job_description)
    job_skills = job_skill_data["skills"]
    job_keywords = extract_job_keywords(job_description, job_skills)
    requirements = extract_job_requirements(job_description)

    # ---------- Step 2: which of those do we have? ----------
    matching_skills = [s for s in job_skills if s in resume_skills]
    missing_skills = [s for s in job_skills if s not in resume_skills]

    # Skills the candidate has that the job did not ask for. Not a
    # negative - they are worth showing as "extra value".
    extra_skills = [s for s in parsed["skills"]["technical"]
                    if s not in job_skills]

    # ---------- Step 3: keyword overlap ----------
    matching_keywords, missing_keywords = [], []
    for word, count in job_keywords:
        # \b...\b so "api" does not match inside "rapidly".
        if re.search(r"\b" + re.escape(word) + r"\b", resume_lower):
            matching_keywords.append(word)
        else:
            missing_keywords.append(word)

    # ---------- Step 4: the percentage ----------
    #
    # Two ratios, weighted 70/30. Each is guarded against divide-by-zero
    # for the case where the job description mentions no skills at all
    # (for example a one-line posting).
    skill_total = len(job_skills)
    keyword_total = len(job_keywords)

    skill_ratio = len(matching_skills) / skill_total if skill_total else 0.0
    keyword_ratio = (len(matching_keywords) / keyword_total
                     if keyword_total else 0.0)

    if skill_total == 0 and keyword_total > 0:
        # No technologies named, so keywords carry the whole score.
        match_percent = round(keyword_ratio * 100)
        weighting_note = ("This job description names no specific "
                          "technologies, so the score is based on keyword "
                          "overlap alone.")
    elif skill_total > 0 and keyword_total < MIN_KEYWORDS_FOR_WEIGHTING:
        # Short posting: not enough keywords to judge, so skills decide.
        match_percent = round(skill_ratio * 100)
        weighting_note = ("This job description is short, so there were "
                          "too few keywords to score reliably. The match "
                          "is based on skill coverage alone.")
    elif skill_total == 0 and keyword_total == 0:
        match_percent = 0
        weighting_note = ("The job description was too short to analyse. "
                          "Paste the full posting for a useful score.")
    else:
        match_percent = round(skill_ratio * 70 + keyword_ratio * 30)
        weighting_note = ("Skills are worth 70% and keywords 30%, because "
                          "a named technology is a hard requirement while "
                          "a keyword is softer language.")

    match_percent = max(0, min(match_percent, 100))   # safety clamp

    grade, grade_color, grade_message = get_match_grade(match_percent)

    # ---------- Step 5: what should they learn first? ----------
    # missing_skills is already ordered by how often the JD mentions each
    # one, so the first entries are the most important to the employer.
    skills_to_learn = [
        {"skill": skill,
         "mentions": job_skill_data["counts"].get(skill, 1)}
        for skill in missing_skills[:8]
    ]

    # ---------- Step 6: experience gap ----------
    resume_years = parsed["experience"]["years"]
    experience_note = ""
    if requirements["years"]:
        if resume_years and resume_years >= requirements["years"]:
            experience_note = (f"The job asks for {requirements['years']}+ "
                               f"years and your resume shows {resume_years}.")
        else:
            experience_note = (
                f"The job asks for {requirements['years']}+ years of "
                "experience. If you are a fresher, lead with projects and "
                "internships that demonstrate the same skills.")

    return {
        "match_percent":     match_percent,
        "grade":             grade,
        "grade_color":       grade_color,
        "grade_message":     grade_message,

        "matching_skills":   matching_skills,
        "missing_skills":    missing_skills,
        "extra_skills":      extra_skills[:12],
        "skills_to_learn":   skills_to_learn,

        "matching_keywords": matching_keywords[:12],
        "missing_keywords":  missing_keywords[:12],

        "job_skills":        job_skills,
        "job_skills_by_category": job_skill_data["by_category"],
        "requirements":      requirements,
        "experience_note":   experience_note,

        # Numbers behind the percentage, shown in the "how was this
        # calculated" panel so the user can check our working.
        "breakdown": {
            "skills_matched":   len(matching_skills),
            "skills_required":  skill_total,
            "skill_percent":    round(skill_ratio * 100),
            "keywords_matched": len(matching_keywords),
            "keywords_total":   keyword_total,
            "keyword_percent":  round(keyword_ratio * 100),
            "note":             weighting_note,
        },
    }


# =====================================================================
# Quick manual test
# =====================================================================
# Run:
#   python -m services.job_matcher uploads\resume.pdf "Python Flask SQL AWS"
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print('Usage: python -m services.job_matcher <pdf> "<job description>"')
        sys.exit(1)

    from services.pdf_parser import extract_text_from_pdf, PDFError
    from services.resume_parser import parse_resume

    try:
        extracted = extract_text_from_pdf(sys.argv[1])
    except PDFError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    parsed_resume = parse_resume(extracted["text"])
    report = match_resume_to_job(parsed_resume, sys.argv[2],
                                 extracted["text"])

    if report is None:
        print("No job description given.")
        sys.exit(0)

    print("=" * 62)
    print(f"  JOB MATCH: {report['match_percent']}%   ({report['grade']})")
    print(f"  {report['grade_message']}")
    print("=" * 62)

    breakdown = report["breakdown"]
    print(f"\n  Skills  : {breakdown['skills_matched']}/"
          f"{breakdown['skills_required']} ({breakdown['skill_percent']}%)")
    print(f"  Keywords: {breakdown['keywords_matched']}/"
          f"{breakdown['keywords_total']} ({breakdown['keyword_percent']}%)")
    print(f"  {breakdown['note']}")

    print(f"\nMATCHING SKILLS ({len(report['matching_skills'])})")
    print("  " + (", ".join(report["matching_skills"]) or "-- none --"))

    print(f"\nMISSING SKILLS ({len(report['missing_skills'])})")
    print("  " + (", ".join(report["missing_skills"]) or "-- none --"))

    print("\nLEARN THESE FIRST")
    for item in report["skills_to_learn"] or []:
        print(f"  - {item['skill']} (mentioned {item['mentions']}x in the JD)")

    print(f"\nMATCHING KEYWORDS\n  "
          + (", ".join(report["matching_keywords"]) or "-- none --"))
    print(f"\nMISSING KEYWORDS\n  "
          + (", ".join(report["missing_keywords"]) or "-- none --"))

    if report["experience_note"]:
        print(f"\nEXPERIENCE\n  {report['experience_note']}")
