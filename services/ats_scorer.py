"""
services/ats_scorer.py
======================
Job of this file: turn the structured data from resume_parser.py into a
single number out of 100, plus an explanation of how that number was
reached.

IMPORTANT - please read and repeat this in your project report:
------------------------------------------------------------------
This is an ESTIMATED, ATS-STYLE score produced by our own rules.
It is NOT the score of any real company's Applicant Tracking System.
Companies like Workday, Taleo and Greenhouse all use different, private
algorithms. What we are measuring is whether a resume follows the habits
that ATS software and recruiters generally reward: clear sections, real
skills, strong verbs and measurable results.
------------------------------------------------------------------

Design principle: TRANSPARENCY
------------------------------
A score with no explanation is useless - the user cannot act on "63/100".
So every category returns three things:

    points   - how many points were earned
    details  - exactly what earned (or lost) those points
    tips     - what to do to gain the missing points

Because of this the scoring is deliberately RULE BASED, not a machine
learning model. Every single point can be traced back to one line of code,
which is also what makes it easy to defend in a viva.

Scoring breakdown (totals 100)
------------------------------
    Contact Information .... 10
    Skills ................. 20
    Education .............. 10
    Projects ............... 15
    Certifications ......... 10
    Keywords ............... 15
    Resume Structure ....... 10
    Readability ............ 10
"""

# ---------------------------------------------------------------------
# Configuration - change these numbers to re-balance the whole score
# ---------------------------------------------------------------------
# Keeping the weights in one dictionary means you can tune the scoring
# without hunting through the functions below.
CATEGORY_WEIGHTS = {
    "contact":        10,
    "skills":         20,
    "education":      10,
    "projects":       15,
    "certifications": 10,
    "keywords":       15,
    "structure":      10,
    "readability":    10,
}

# Friendly labels shown on the dashboard.
CATEGORY_LABELS = {
    "contact":        "Contact Information",
    "skills":         "Skills",
    "education":      "Education",
    "projects":       "Projects",
    "certifications": "Certifications",
    "keywords":       "Keywords & Impact",
    "structure":      "Resume Structure",
    "readability":    "Readability",
}

CATEGORY_ICONS = {
    "contact":        "person-vcard",
    "skills":         "cpu",
    "education":      "mortarboard",
    "projects":       "kanban",
    "certifications": "patch-check",
    "keywords":       "key",
    "structure":      "diagram-3",
    "readability":    "book",
}

# A resume that is too short looks empty; too long and recruiters skim it.
# 350-800 words is the range most fresher resumes sit in.
IDEAL_WORD_MIN = 350
IDEAL_WORD_MAX = 800


# ---------------------------------------------------------------------
# Small helper
# ---------------------------------------------------------------------

def _scale(value, best_value, max_points):
    """
    Award points on a sliding scale instead of all-or-nothing.

    Example: _scale(3, 5, 10) means
        "you have 3 of the 5 we hope for, so you get 6 of 10 points."

    Having 2 projects should clearly beat having 0, but should not score
    the same as having 5. A sliding scale expresses that.

    Anything at or above best_value earns the full max_points.
    """
    if best_value <= 0:
        return 0.0
    ratio = min(value, best_value) / best_value
    return round(ratio * max_points, 2)


# ---------------------------------------------------------------------
# CATEGORY 1 - Contact Information (10 points)
# ---------------------------------------------------------------------

def score_contact(parsed):
    """
    An ATS must be able to find how to reach you. A resume with no email
    is literally unusable, so this category is all about presence.

    Points:  name 1 | email 3 | phone 2 | LinkedIn 2 | GitHub 2
    """
    contact = parsed["contact"]
    points = 0.0
    details, tips = [], []

    # Each item is: (value, points it is worth, label, tip if missing)
    checks = [
        (contact.get("name"),     1, "Name detected",
         "Put your full name alone on the first line."),
        (contact.get("email"),    3, "Email address found",
         "Add a professional email address."),
        (contact.get("phone"),    2, "Phone number found",
         "Add a phone number with your country code."),
        (contact.get("linkedin"), 2, "LinkedIn profile linked",
         "Add your LinkedIn URL - recruiters check it first."),
        (contact.get("github"),   2, "GitHub profile linked",
         "Add your GitHub URL so they can see your code."),
    ]

    for value, worth, found_message, missing_tip in checks:
        if value:
            points += worth
            details.append(f"+{worth} {found_message}")
        else:
            tips.append(missing_tip)

    return points, details, tips


# ---------------------------------------------------------------------
# CATEGORY 2 - Skills (20 points)
# ---------------------------------------------------------------------

def score_skills(parsed):
    """
    Skills carry the most weight (20) because keyword matching is what an
    ATS does above everything else.

    We reward three different things, not just a long list:

      12 pts  how many technical skills we recognised  (12 is full marks)
       5 pts  how many CATEGORIES they spread across   (breadth)
       3 pts  soft skills mentioned

    Why reward breadth separately? A candidate listing 12 programming
    languages and nothing else is weaker than one with languages +
    a database + a cloud platform + Git. Breadth shows a complete profile.
    """
    skills = parsed["skills"]
    technical_count = skills["technical_count"]
    category_count = len(skills["by_category"])
    soft_count = skills["soft_count"]

    details, tips = [], []

    quantity_points = _scale(technical_count, 12, 12)
    breadth_points = _scale(category_count, 5, 5)
    soft_points = _scale(soft_count, 3, 3)

    points = quantity_points + breadth_points + soft_points

    details.append(
        f"+{quantity_points} {technical_count} technical skill(s) recognised")
    details.append(
        f"+{breadth_points} covering {category_count} skill categor(y/ies)")
    details.append(f"+{soft_points} {soft_count} soft skill(s) mentioned")

    if technical_count < 12:
        tips.append(
            f"List more technical skills - you have {technical_count}, "
            "aim for at least 12 relevant ones.")
    if category_count < 5:
        tips.append(
            "Broaden your skill mix: languages, web, databases, cloud "
            "and tools. Breadth shows a complete profile.")
    if soft_count < 3:
        tips.append(
            "Mention soft skills through actions, e.g. "
            '"Collaborated with a team of 5 engineers".')

    return points, details, tips


# ---------------------------------------------------------------------
# CATEGORY 3 - Education (10 points)
# ---------------------------------------------------------------------

def score_education(parsed):
    """
    For a fresher, education is a core section.

    Points:  section exists 4 | degree named 3 | grade shown 2 | year shown 1
    """
    education = parsed["education"]
    has_section = parsed["sections"]["found"].get("education", False)

    points = 0.0
    details, tips = [], []

    if has_section:
        points += 4
        details.append("+4 Education section found")
    else:
        tips.append("Add a clearly titled EDUCATION section.")

    if education["degrees"]:
        points += 3
        details.append(
            f"+3 Degree recognised: {', '.join(education['degrees'][:2])}")
    else:
        tips.append(
            "Write your degree in a standard form, e.g. "
            '"B.Tech Computer Science Engineering".')

    if education["grades"]:
        points += 2
        details.append(f"+2 Grade shown: {education['grades'][0]}")
    else:
        tips.append("Add your CGPA or percentage - recruiters filter on it.")

    if education["years"]:
        points += 1
        details.append(f"+1 Year(s) shown: {', '.join(education['years'][-2:])}")
    else:
        tips.append("Add your start and graduation years.")

    return points, details, tips


# ---------------------------------------------------------------------
# CATEGORY 4 - Projects (15 points)
# ---------------------------------------------------------------------

def score_projects(parsed):
    """
    Projects are the strongest signal a fresher has, because they are the
    only proof of real work. Weighted 15 for that reason.

    Points:  section exists 4 | number of projects 6 | measurable results 5

    The "measurable results" part is the one most students lose. Compare:
        "Built a web app"                          <- no proof
        "Built a web app used by 1200 students"    <- proof
    """
    projects = parsed["projects"]
    has_section = parsed["sections"]["found"].get("projects", False)

    points = 0.0
    details, tips = [], []

    if has_section:
        points += 4
        details.append("+4 Projects section found")
    else:
        tips.append("Add a PROJECTS section - it is the most important "
                    "section for a fresher.")

    count_points = _scale(projects["count"], 3, 6)
    points += count_points
    details.append(f"+{count_points} {projects['count']} project line(s) found")

    quantified_points = _scale(projects["quantified_count"], 2, 5)
    points += quantified_points
    details.append(
        f"+{quantified_points} {projects['quantified_count']} project line(s) "
        "contain measurable numbers")

    if projects["count"] < 3:
        tips.append("Describe at least 2-3 projects, each with 2-3 bullet "
                    "points explaining what you built and with what.")
    if projects["quantified_count"] < 2:
        tips.append(
            'Add numbers to your project descriptions, e.g. "reduced load '
            'time by 40%" instead of "improved performance".')

    return points, details, tips


# ---------------------------------------------------------------------
# CATEGORY 5 - Certifications (10 points)
# ---------------------------------------------------------------------

def score_certifications(parsed):
    """
    Certifications show initiative and are easy keyword matches for an ATS.

    Points:  section exists 4 | number of certifications 6
    """
    certifications = parsed["certifications"]
    has_section = parsed["sections"]["found"].get("certifications", False)

    points = 0.0
    details, tips = [], []

    if has_section:
        points += 4
        details.append("+4 Certifications section found")
    else:
        tips.append("Add a CERTIFICATIONS section, even for free courses.")

    count_points = _scale(certifications["count"], 3, 6)
    points += count_points
    details.append(
        f"+{count_points} {certifications['count']} certification(s) listed")

    if certifications["count"] < 3:
        tips.append("List 3 or more certifications relevant to your target "
                    "role, with the issuing body and year.")

    return points, details, tips


# ---------------------------------------------------------------------
# CATEGORY 6 - Keywords & Impact (15 points)
# ---------------------------------------------------------------------

def score_keywords(parsed):
    """
    This category measures HOW things are written, not what exists.

    Points:
       7  strong action verbs used   (developed, optimised, led...)
       5  numbers used anywhere      (40%, 1200 users, 3 months)
       3  a rich enough skill vocabulary (8+ technical skills)

    Why action verbs? Compare these two lines:
        "Was responsible for the database"   <- passive, weak
        "Designed and optimised the database" <- active, strong
    Recruiters scan for the second style, and so do keyword filters.
    """
    stats = parsed["stats"]
    details, tips = [], []

    verb_points = _scale(stats["action_verb_count"], 8, 7)
    number_points = _scale(stats["quantified_count"], 5, 5)
    vocabulary_points = _scale(parsed["skills"]["technical_count"], 8, 3)

    points = verb_points + number_points + vocabulary_points

    details.append(
        f"+{verb_points} {stats['action_verb_count']} distinct action verb(s) used")
    details.append(
        f"+{number_points} {stats['quantified_count']} measurable number(s) found")
    details.append(
        f"+{vocabulary_points} technical keyword coverage")

    if stats["action_verb_count"] < 8:
        tips.append(
            "Start bullet points with strong verbs: Developed, Designed, "
            "Optimised, Automated, Led, Reduced, Implemented.")
    if stats["quantified_count"] < 5:
        tips.append(
            "Quantify your work wherever possible: how many users, how "
            "much faster, how many records, what percentage.")

    return points, details, tips


# ---------------------------------------------------------------------
# CATEGORY 7 - Resume Structure (10 points)
# ---------------------------------------------------------------------

def score_structure(parsed):
    """
    Can an ATS actually navigate the document?

    Points:  sections present 7 | bullet points used 3

    An ATS splits a resume by its headings. A resume written as one long
    paragraph has nothing to split on, so everything lands in the wrong
    field - or nowhere at all.
    """
    stats = parsed["stats"]
    sections = parsed["sections"]

    details, tips = [], []

    section_points = _scale(stats["sections_present"],
                            stats["sections_total"], 7)
    bullet_points = _scale(stats["bullet_count"], 8, 3)

    points = section_points + bullet_points

    details.append(
        f"+{section_points} {stats['sections_present']} of "
        f"{stats['sections_total']} standard sections present")
    details.append(f"+{bullet_points} {stats['bullet_count']} bullet point(s) used")

    missing_labels = [s["label"] for s in sections["missing"]]
    if missing_labels:
        tips.append("Add the missing section(s): " + ", ".join(missing_labels) + ".")
    if stats["bullet_count"] < 8:
        tips.append("Use bullet points instead of paragraphs - both ATS "
                    "software and human recruiters parse them better.")

    return points, details, tips


# ---------------------------------------------------------------------
# CATEGORY 8 - Readability (10 points)
# ---------------------------------------------------------------------

def score_readability(parsed):
    """
    Is the resume a comfortable length and easy to scan?

    Points:  good overall length 5 | short lines 3 | one page-ish density 2

    Note on "average words per line": a resume line should read like a
    bullet, roughly 8-18 words. Averages above ~25 usually mean dense
    paragraphs, which recruiters skip.
    """
    stats = parsed["stats"]
    word_count = stats["word_count"]
    line_count = max(stats["line_count"], 1)     # never divide by zero

    details, tips = [], []
    points = 0.0

    # --- Guard: an almost empty resume must score zero here ---
    # Without this check a blank resume earned points for "lines are easy
    # to scan", simply because it had no long lines. Scoring the absence
    # of content as good readability is clearly wrong.
    if word_count < 50:
        tips.append("We found almost no readable text. Make sure your PDF "
                    "contains real text and not a scanned image.")
        return 0.0, ["+0 Not enough text to judge readability"], tips

    # --- Part 1: total length (5 points) ---
    if IDEAL_WORD_MIN <= word_count <= IDEAL_WORD_MAX:
        points += 5
        details.append(f"+5 Good length ({word_count} words)")
    elif 250 <= word_count < IDEAL_WORD_MIN or IDEAL_WORD_MAX < word_count <= 1000:
        points += 3
        details.append(f"+3 Acceptable length ({word_count} words)")
        if word_count < IDEAL_WORD_MIN:
            tips.append(f"Your resume is short ({word_count} words). "
                        "Expand your project and skill descriptions.")
        else:
            tips.append(f"Your resume is long ({word_count} words). "
                        "Trim it towards one page.")
    else:
        points += 1
        details.append(f"+1 Length is outside the usual range "
                       f"({word_count} words)")
        tips.append(f"Aim for {IDEAL_WORD_MIN}-{IDEAL_WORD_MAX} words. "
                    f"You currently have {word_count}.")

    # --- Part 2: average words per line (3 points) ---
    words_per_line = word_count / line_count
    if words_per_line <= 18:
        points += 3
        details.append(f"+3 Lines are easy to scan "
                       f"({words_per_line:.1f} words per line)")
    elif words_per_line <= 25:
        points += 2
        details.append(f"+2 Lines are slightly long "
                       f"({words_per_line:.1f} words per line)")
        tips.append("Break long lines into shorter bullet points.")
    else:
        details.append(f"+0 Lines are very long "
                       f"({words_per_line:.1f} words per line)")
        tips.append("Your resume reads like paragraphs. Convert them into "
                    "short bullet points of 8-18 words.")

    # --- Part 3: enough content lines to look like a resume (2 points) ---
    if line_count >= 20:
        points += 2
        details.append(f"+2 {line_count} content lines - good density")
    elif line_count >= 10:
        points += 1
        details.append(f"+1 {line_count} content lines")
        tips.append("Add more detail - a resume usually has 25+ lines.")
    else:
        tips.append("The resume looks almost empty. Add real content under "
                    "each section.")

    return points, details, tips


# ---------------------------------------------------------------------
# Grade bands
# ---------------------------------------------------------------------

def get_grade(total):
    """
    Turn a number into a word plus a Bootstrap colour name.

    Returns (label, bootstrap_colour, one-line message).
    """
    if total >= 85:
        return ("Excellent", "success",
                "Your resume is ATS-friendly and well structured.")
    if total >= 70:
        return ("Good", "success",
                "A solid resume. A few changes will make it stronger.")
    if total >= 55:
        return ("Average", "warning",
                "The basics are there, but several sections need work.")
    if total >= 40:
        return ("Needs Work", "warning",
                "Important pieces are missing. Follow the tips below.")
    return ("Poor", "danger",
            "This resume will struggle with automated screening.")


# ---------------------------------------------------------------------
# THE MAIN FUNCTION
# ---------------------------------------------------------------------

# Maps each category key to the function that scores it. Adding a new
# category means adding one line here and one entry in CATEGORY_WEIGHTS -
# the loop below and the whole template adapt automatically.
SCORING_FUNCTIONS = {
    "contact":        score_contact,
    "skills":         score_skills,
    "education":      score_education,
    "projects":       score_projects,
    "certifications": score_certifications,
    "keywords":       score_keywords,
    "structure":      score_structure,
    "readability":    score_readability,
}


def calculate_ats_score(parsed):
    """
    Run every category scorer and assemble the final report.

    Parameter
    ---------
    parsed : dict
        The output of services.resume_parser.parse_resume()

    Returns
    -------
    dict with:
        total        int    0-100
        grade        str    "Good"
        grade_color  str    Bootstrap colour name
        grade_message str
        categories   list   one entry per category, with points and tips
        strengths    list   categories scoring 80% or more
        improvements list   the most valuable tips, best-first
    """
    categories = []
    raw_total = 0.0

    for key, scoring_function in SCORING_FUNCTIONS.items():
        max_points = CATEGORY_WEIGHTS[key]

        points, details, tips = scoring_function(parsed)

        # Safety clamp: never let a bug push a category above its weight
        # or below zero. Defensive programming - one wrong line in a
        # scorer should not produce "112 / 100" on screen.
        points = max(0.0, min(points, max_points))
        raw_total += points

        percent = round(points / max_points * 100) if max_points else 0

        # A simple traffic light for the UI.
        if percent >= 80:
            status = "success"
        elif percent >= 50:
            status = "warning"
        else:
            status = "danger"

        categories.append({
            "key":     key,
            "label":   CATEGORY_LABELS[key],
            "icon":    CATEGORY_ICONS[key],
            "score":   round(points, 1),
            "max":     max_points,
            "percent": percent,
            "status":  status,
            "details": details,
            "tips":    tips,
        })

    total = int(round(raw_total))
    total = max(0, min(total, 100))          # clamp again, just in case

    grade, grade_color, grade_message = get_grade(total)

    # Strengths = the categories the user already does well.
    strengths = [c for c in categories if c["percent"] >= 80]

    # Improvements = every tip, ordered so the biggest wins come first.
    # We sort by how many points are actually available in that category,
    # because fixing a 20-point category matters more than a 10-point one.
    improvements = []
    for category in sorted(categories,
                           key=lambda c: c["max"] - c["score"],
                           reverse=True):
        for tip in category["tips"]:
            improvements.append({
                "category": category["label"],
                "tip": tip,
                "points_available": round(category["max"] - category["score"], 1),
            })

    return {
        "total":         total,
        "grade":         grade,
        "grade_color":   grade_color,
        "grade_message": grade_message,
        "categories":    categories,
        "strengths":     strengths,
        "improvements":  improvements,
        "points_lost":   round(100 - raw_total, 1),
    }


# =====================================================================
# Quick manual test
# =====================================================================
# Run:  python -m services.ats_scorer uploads\some_resume.pdf
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m services.ats_scorer <path-to-pdf>")
        sys.exit(1)

    from services.pdf_parser import extract_text_from_pdf, PDFError
    from services.resume_parser import parse_resume

    try:
        extracted = extract_text_from_pdf(sys.argv[1])
    except PDFError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    report = calculate_ats_score(parse_resume(extracted["text"]))

    print("=" * 62)
    print(f"  ATS SCORE: {report['total']} / 100   ({report['grade']})")
    print(f"  {report['grade_message']}")
    print("=" * 62)

    for category in report["categories"]:
        bar_filled = int(category["percent"] / 5)
        bar = "#" * bar_filled + "." * (20 - bar_filled)
        print(f"\n{category['label']:22s} {category['score']:>5} / "
              f"{category['max']:<3} [{bar}] {category['percent']}%")
        for detail in category["details"]:
            print(f"    {detail}")

    print("\n" + "=" * 62)
    print("  TOP IMPROVEMENTS")
    print("=" * 62)
    for index, item in enumerate(report["improvements"][:8], start=1):
        print(f"  {index}. [{item['category']}] {item['tip']}")

    print("\nNOTE: this is an estimated ATS-style score, not the score of")
    print("any specific company's applicant tracking system.")
