"""
services/skills_data.py
=======================
The "skill dictionary" of the project - pure data, no logic.

Why is this a separate file?
---------------------------
resume_parser.py contains the *logic* (how to find things in text).
This file contains the *data* (what to look for). Keeping them apart means:

  * You can add a new skill without touching or breaking any code.
  * A teammate who does not know Python can still extend the list.
  * The parser file stays short and readable instead of being buried
    under 200 lines of skill names.

HOW TO ADD A NEW SKILL
----------------------
Find the right category below and add one line:

        "Kubernetes": ["kubernetes", "k8s"],
         ^ display name  ^ everything we search for, in lowercase

The first value is what the user sees on screen. The list holds every
spelling that should count as that skill (aliases, abbreviations,
versions). Always write aliases in lowercase - matching is
case-insensitive, so "Python", "PYTHON" and "python" all match "python".
"""

# ---------------------------------------------------------------------
# TECHNICAL SKILLS
# ---------------------------------------------------------------------
# Structure:  { "Category name": { "Display name": [aliases...] } }
#
# The categories below are exactly the ones shown on the dashboard.
# Adding a brand new category here automatically adds it to the UI -
# no template changes needed.
TECHNICAL_SKILLS = {

    "Programming Languages": {
        "Python":      ["python", "python3"],
        "Java":        ["java"],
        "C":           ["c"],                       # ambiguous - see note below
        "C++":         ["c++", "cpp", "c plus plus"],
        "C#":          ["c#", "c sharp", "csharp"],
        "JavaScript":  ["javascript", "java script"],
        "TypeScript":  ["typescript"],
        "Go":          ["go", "golang"],            # ambiguous - see note below
        "R":           ["r"],                       # ambiguous - see note below
        "PHP":         ["php"],
        "Ruby":        ["ruby"],
        "Swift":       ["swift"],
        "Kotlin":      ["kotlin"],
        "Scala":       ["scala"],
        "MATLAB":      ["matlab"],
        "Shell Script": ["bash", "shell scripting", "shell script"],
    },

    "Web Technologies": {
        "HTML":        ["html", "html5"],
        "CSS":         ["css", "css3"],
        "React":       ["react", "reactjs", "react.js"],
        "Angular":     ["angular", "angularjs"],
        "Vue.js":      ["vue", "vuejs", "vue.js"],
        "Node.js":     ["node.js", "nodejs", "node js"],
        "Express.js":  ["express", "expressjs", "express.js"],
        "Flask":       ["flask"],
        "Django":      ["django"],
        "Spring Boot": ["spring boot", "springboot", "spring"],
        "Bootstrap":   ["bootstrap"],
        "Tailwind CSS": ["tailwind", "tailwindcss", "tailwind css"],
        "jQuery":      ["jquery"],
        "REST API":    ["rest api", "restful api", "rest apis", "restful",
                        "rest"],
        "GraphQL":     ["graphql"],
        ".NET":        [".net", "dotnet", "asp.net"],
    },

    "Databases": {
        "SQL":         ["sql"],
        "MySQL":       ["mysql"],
        "PostgreSQL":  ["postgresql", "postgres"],
        "MongoDB":     ["mongodb", "mongo db"],
        "SQLite":      ["sqlite"],
        "Oracle":      ["oracle db", "oracle database", "pl/sql", "plsql"],
        "Redis":       ["redis"],
        "Firebase":    ["firebase", "firestore"],
        "Microsoft SQL Server": ["sql server", "mssql", "ms sql"],
    },

    "Cloud": {
        "AWS":          ["aws", "amazon web services", "ec2", "s3 bucket"],
        "Azure":        ["azure", "microsoft azure"],
        "Google Cloud": ["google cloud", "gcp", "google cloud platform"],
        "Heroku":       ["heroku"],
        "Netlify":      ["netlify"],
        "Vercel":       ["vercel"],
        "Cloudflare":   ["cloudflare"],
    },

    "Tools": {
        "Git":         ["git"],
        "GitHub":      ["github"],
        "GitLab":      ["gitlab"],
        "Docker":      ["docker"],
        "Kubernetes":  ["kubernetes", "k8s"],
        "Jenkins":     ["jenkins"],
        "Postman":     ["postman"],
        "Jira":        ["jira"],
        "Linux":       ["linux", "ubuntu"],
        "VS Code":     ["vs code", "visual studio code"],
        "Figma":       ["figma"],
        "Excel":       ["excel", "ms excel", "microsoft excel"],
        "Power BI":    ["power bi", "powerbi"],
        "Tableau":     ["tableau"],
    },

    "AI/ML": {
        "Machine Learning":        ["machine learning", "ml"],
        "Deep Learning":           ["deep learning"],
        "Artificial Intelligence": ["artificial intelligence", "ai"],
        "NLP":                     ["nlp", "natural language processing"],
        "Computer Vision":         ["computer vision", "opencv"],
        "Data Science":            ["data science"],
        "Data Analysis":           ["data analysis", "data analytics"],
        "TensorFlow":              ["tensorflow"],
        "PyTorch":                 ["pytorch"],
        "Scikit-learn":            ["scikit-learn", "sklearn", "scikit learn"],
        "Pandas":                  ["pandas"],
        "NumPy":                   ["numpy"],
        "Matplotlib":              ["matplotlib"],
        "Keras":                   ["keras"],
    },

    "Other Technical Skills": {
        "Data Structures":   ["data structures", "dsa"],
        "Algorithms":        ["algorithms", "algorithm design"],
        "OOP":               ["oop", "object oriented programming",
                              "object-oriented programming"],
        "Operating Systems": ["operating systems", "operating system"],
        "Computer Networks": ["computer networks", "networking"],
        "DBMS":              ["dbms", "database management system"],
        "Agile":             ["agile", "scrum"],
        "Unit Testing":      ["unit testing", "pytest", "junit"],
        "CI/CD":             ["ci/cd", "continuous integration"],
        "API Integration":   ["api integration"],
    },
}


# ---------------------------------------------------------------------
# AMBIGUOUS SKILLS
# ---------------------------------------------------------------------
# Some skill names are also ordinary English words or single letters:
#
#   "C"  appears inside almost any sentence as a stray letter
#   "R"  same problem
#   "Go" appears in "go to", "going", "ongoing"
#   "AI" / "ML" appear in many unrelated phrases
#
# Searching for these in the WHOLE resume produces false positives, and a
# wrong skill is worse than a missing one - the user would trust it.
#
# So these skills are only counted if they appear inside the resume's
# Skills section, where a single letter really does mean the language.
AMBIGUOUS_SKILLS = {"C", "R", "Go", "Artificial Intelligence",
                    "Machine Learning"}


# ---------------------------------------------------------------------
# SOFT SKILLS
# ---------------------------------------------------------------------
# Simple flat dictionary: { "Display name": [aliases...] }
SOFT_SKILLS = {
    "Communication":        ["communication", "communication skills",
                             "verbal communication", "written communication"],
    "Teamwork":             ["teamwork", "team work", "team player",
                             "collaboration", "collaborative"],
    "Leadership":           ["leadership", "team lead", "led a team"],
    "Problem Solving":      ["problem solving", "problem-solving"],
    "Time Management":      ["time management"],
    "Adaptability":         ["adaptability", "adaptable", "flexibility"],
    "Critical Thinking":    ["critical thinking"],
    "Creativity":           ["creativity", "creative thinking"],
    "Analytical Skills":    ["analytical", "analytical skills"],
    "Presentation Skills":  ["presentation skills", "public speaking"],
    "Attention to Detail":  ["attention to detail", "detail oriented",
                             "detail-oriented"],
    "Decision Making":      ["decision making", "decision-making"],
    "Interpersonal Skills": ["interpersonal", "interpersonal skills"],
    "Self Motivated":       ["self motivated", "self-motivated",
                             "self starter", "self-starter"],
    "Mentoring":            ["mentoring", "mentorship", "coaching"],
}


# ---------------------------------------------------------------------
# ACTION VERBS
# ---------------------------------------------------------------------
# Strong verbs that make a bullet point sound like an achievement.
# Used in Phase 4 (ATS scoring) and Phase 5 (AI suggestions).
ACTION_VERBS = [
    "achieved", "built", "created", "designed", "developed", "engineered",
    "implemented", "improved", "increased", "reduced", "optimized",
    "optimised", "automated", "launched", "led", "managed", "migrated",
    "deployed", "integrated", "delivered", "analyzed", "analysed",
    "collaborated", "coordinated", "streamlined", "architected",
    "programmed", "tested", "debugged", "maintained", "trained",
]


# ---------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------

def all_technical_skills():
    """
    Return one flat dictionary of every technical skill.

    Turns the two-level structure
        {"Databases": {"MySQL": [...]}}
    into the flat one
        {"MySQL": [...]}

    Useful when we only care about matching and not about categories.
    """
    flat = {}
    for skills_in_category in TECHNICAL_SKILLS.values():
        flat.update(skills_in_category)
    return flat


def category_of(skill_name):
    """
    Given a display name like "MySQL", return "Databases".
    Returns "Other Technical Skills" if it is not found.
    """
    for category, skills in TECHNICAL_SKILLS.items():
        if skill_name in skills:
            return category
    return "Other Technical Skills"


def total_skill_count():
    """How many technical skills the database knows about."""
    return len(all_technical_skills())
