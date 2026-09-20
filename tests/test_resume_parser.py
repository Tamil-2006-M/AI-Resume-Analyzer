"""Tests for services/resume_parser.py"""

from services.resume_parser import (
    parse_resume, detect_sections, extract_skills,
    extract_contact_info, _find_phone, _match_section_key,
)


class TestContactExtraction:
    def test_finds_email(self, parsed_good):
        assert parsed_good["contact"]["email"] == "priya.v99@example.com"

    def test_finds_phone(self, parsed_good):
        phone = parsed_good["contact"]["phone"]
        assert phone and "98400" in phone

    def test_finds_linkedin_and_github(self, parsed_good):
        assert "linkedin.com" in parsed_good["contact"]["linkedin"]
        assert "github.com" in parsed_good["contact"]["github"]

    def test_finds_name(self, parsed_good):
        assert parsed_good["contact"]["name"] == "Priya Venkatesan"

    def test_returns_none_rather_than_guessing(self):
        """
        The honesty rule: when a value is absent we return None, never a
        plausible-looking guess the user might believe.
        """
        result = extract_contact_info("Just some words here.", "Just some words")
        assert result["email"] is None
        assert result["phone"] is None
        assert result["linkedin"] is None

    def test_degree_is_not_mistaken_for_a_website(self):
        """B.Tech was once reported as a portfolio, because .tech is a TLD."""
        result = extract_contact_info("B.Tech Computer Science", "B.Tech")
        assert result["portfolio"] is None


class TestPhoneDetection:
    def test_accepts_real_formats(self):
        for number in ["9876543210", "+91 98765 43210", "+91-98765-43210",
                       "555-123-4567"]:
            assert _find_phone(number) is not None, number

    def test_rejects_a_year_range(self):
        """"2022 - 2026" must not be read as a phone number."""
        assert _find_phone("Studied 2022 - 2026") is None

    def test_rejects_a_cgpa(self):
        assert _find_phone("CGPA 8.7 / 10") is None


class TestSectionDetection:
    def test_finds_every_section_of_a_complete_resume(self, parsed_good):
        assert parsed_good["stats"]["sections_present"] == 8

    def test_detects_all_caps_headings(self):
        sections = detect_sections("EDUCATION\nB.Tech CSE at some college")
        assert sections["found"]["education"] is True

    def test_detects_title_case_headings(self):
        sections = detect_sections("Work Experience\nIntern at Example Corp")
        assert sections["found"]["experience"] is True

    def test_a_sentence_is_not_a_heading(self):
        """The classic false positive this rule exists to prevent."""
        assert _match_section_key("Developed projects using Python") is None

    def test_a_heading_with_a_full_stop_is_not_a_heading(self):
        assert _match_section_key("Projects.") is None

    def test_an_empty_section_does_not_count_as_present(self):
        sections = detect_sections("PROJECTS\n\nSKILLS\nPython, SQL")
        assert sections["found"]["projects"] is False
        assert sections["found"]["skills"] is True


class TestSkillExtraction:
    def test_java_and_javascript_are_told_apart(self, parsed_good):
        skills = parsed_good["skills"]["technical"]
        assert "Java" in skills and "JavaScript" in skills

    def test_javascript_alone_does_not_imply_java(self):
        result = extract_skills("TECHNICAL SKILLS\nJavaScript, React",
                                "JavaScript, React")
        assert "Java" not in result["technical"]

    def test_mysql_alone_does_not_imply_sql(self):
        result = extract_skills("Databases: MySQL", "Databases: MySQL")
        assert "MySQL" in result["technical"]
        assert "SQL" not in result["technical"]

    def test_html5_counts_as_html(self):
        result = extract_skills("Web: HTML5, CSS3", "Web: HTML5, CSS3")
        assert "HTML" in result["technical"]
        assert "CSS" in result["technical"]

    def test_c_is_found_inside_a_skills_list(self, parsed_good):
        assert "C" in parsed_good["skills"]["technical"]
        assert "C++" in parsed_good["skills"]["technical"]

    def test_ambiguous_skills_are_ignored_outside_the_skills_section(self):
        """'go' in ordinary prose must not become the Go language."""
        result = extract_skills("We are ready to go the extra mile.", "")
        assert "Go" not in result["technical"]

    def test_skills_are_grouped_into_categories(self, parsed_good):
        by_category = parsed_good["skills"]["by_category"]
        assert "Programming Languages" in by_category
        assert "Databases" in by_category

    def test_soft_skills_are_detected(self, parsed_good):
        assert len(parsed_good["skills"]["soft"]) >= 2


class TestSectionContent:
    def test_reads_education(self, parsed_good):
        assert parsed_good["education"]["degrees"]
        assert parsed_good["education"]["grades"]

    def test_counts_projects(self, parsed_good):
        assert parsed_good["projects"]["count"] >= 2

    def test_spots_measurable_results(self, parsed_good):
        assert parsed_good["projects"]["quantified_count"] >= 1

    def test_counts_certifications(self, parsed_good):
        assert parsed_good["certifications"]["count"] >= 2


class TestNeverCrashes:
    """
    The parser runs on whatever a stranger uploads. It must survive
    anything without raising.
    """

    def test_survives_odd_input(self):
        for text in ["", "   ", "\n\n\n", "a", "x" * 50000,
                     "日本語のテキスト", "\u0000\u0001"]:
            result = parse_resume(text)
            assert "contact" in result
            assert "stats" in result
