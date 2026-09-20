"""Tests for services/job_matcher.py"""

from services.job_matcher import (
    match_resume_to_job, extract_job_skills, extract_job_keywords,
    extract_job_requirements, get_match_grade,
)
from services.resume_parser import parse_resume

BACKEND_JD = """Senior Python Developer - Backend

We are looking for a Python developer to build and maintain scalable
backend services. You will design REST APIs using Flask, write and
optimise SQL queries against MySQL, containerise services with Docker,
and deploy to AWS. You will write unit tests, review pull requests, and
work in an agile team using Git.

Requirements: strong Python and Flask experience, SQL and database
design, familiarity with Docker and AWS, version control with Git,
debugging and performance optimisation. 2+ years experience.
B.Tech in Computer Science required."""


class TestNoJobDescription:
    def test_returns_none_so_the_section_is_skipped(self, parsed_good):
        assert match_resume_to_job(parsed_good, "", "text") is None
        assert match_resume_to_job(parsed_good, "   ", "text") is None
        assert match_resume_to_job(parsed_good, None, "text") is None


class TestMatchPercentage:
    def test_always_between_0_and_100(self, parsed_good, good_text):
        for jd in [BACKEND_JD, "Hi", "Python " * 500,
                   "We need a friendly person."]:
            report = match_resume_to_job(parsed_good, jd, good_text)
            assert 0 <= report["match_percent"] <= 100

    def test_matching_every_skill_scores_100(self):
        parsed = parse_resume(
            "TECHNICAL SKILLS\nPython, Flask, SQL, Git, AWS, Docker\n"
            "PROJECTS\n- Built a thing")
        report = match_resume_to_job(
            parsed, "Need Python, Flask, SQL, Git, AWS and Docker.",
            "Python Flask SQL Git AWS Docker")
        assert report["missing_skills"] == []
        assert report["match_percent"] == 100

    def test_short_job_description_is_scored_on_skills_alone(self):
        """
        Regression test. A short posting yields almost no keywords once
        skills and stop words are removed, so the keyword half of the
        formula had nothing to score - and a candidate matching EVERY
        required skill was still capped at 70%.
        """
        parsed = parse_resume(
            "TECHNICAL SKILLS\nPython, Flask, SQL, Git\nPROJECTS\n- x")
        report = match_resume_to_job(parsed, "Need Python, Flask, SQL, Git.",
                                     "Python Flask SQL Git")
        assert report["match_percent"] == 100
        assert "skill coverage alone" in report["breakdown"]["note"]

    def test_matching_and_missing_never_overlap(self, parsed_good, good_text):
        report = match_resume_to_job(parsed_good, BACKEND_JD, good_text)
        assert not (set(report["matching_skills"]) &
                    set(report["missing_skills"]))

    def test_the_two_lists_together_are_what_the_job_asked_for(
            self, parsed_good, good_text):
        report = match_resume_to_job(parsed_good, BACKEND_JD, good_text)
        assert (len(report["matching_skills"]) + len(report["missing_skills"])
                == len(report["job_skills"]))


class TestJobSkillExtraction:
    def test_finds_the_named_technologies(self):
        skills = extract_job_skills(BACKEND_JD)["skills"]
        for expected in ["Python", "Flask", "Docker", "AWS", "Git", "MySQL"]:
            assert expected in skills, expected

    def test_go_in_prose_is_not_the_go_language(self):
        """The reason _line_looks_like_a_skill_list exists."""
        for prose in ["We want a go-getter ready to go the extra mile.",
                      "Willing to go above and beyond."]:
            assert "Go" not in extract_job_skills(prose)["skills"]

    def test_go_in_a_real_list_is_the_go_language(self):
        skills = extract_job_skills("Languages: Go, Rust, C, Python")["skills"]
        assert "Go" in skills and "C" in skills

    def test_slash_separated_lists_work(self):
        skills = extract_job_skills("Experience with C/C++/Python")["skills"]
        assert "C" in skills and "C++" in skills

    def test_most_mentioned_skill_comes_first(self):
        skills = extract_job_skills(
            "Python Python Python and a little Docker")["skills"]
        assert skills[0] == "Python"


class TestKeywords:
    def test_stop_words_are_removed(self):
        keywords = dict(extract_job_keywords(BACKEND_JD, []))
        for stop_word in ["the", "and", "with", "you", "experience"]:
            assert stop_word not in keywords

    def test_skill_words_are_not_double_counted(self):
        keywords = dict(extract_job_keywords(BACKEND_JD, ["Python", "Docker"]))
        assert "python" not in keywords
        assert "docker" not in keywords


class TestRequirements:
    def test_reads_years_of_experience(self):
        assert extract_job_requirements(BACKEND_JD)["years"] == 2

    def test_reads_the_degree(self):
        degrees = extract_job_requirements(BACKEND_JD)["degrees"]
        assert any("tech" in d.lower() for d in degrees)

    def test_no_years_mentioned_means_fresher_friendly(self):
        assert extract_job_requirements(
            "Python developer wanted.")["is_fresher_friendly"] is True

    def test_five_years_is_not_fresher_friendly(self):
        assert extract_job_requirements(
            "5+ years required.")["is_fresher_friendly"] is False


class TestGrades:
    def test_bands(self):
        assert get_match_grade(90)[0] == "Excellent Match"
        assert get_match_grade(65)[0] == "Good Match"
        assert get_match_grade(45)[0] == "Partial Match"
        assert get_match_grade(10)[0] == "Weak Match"
