"""Tests for services/ats_scorer.py"""

from services.ats_scorer import (
    calculate_ats_score, get_grade, _scale, CATEGORY_WEIGHTS,
)
from services.resume_parser import parse_resume


class TestScoreBounds:
    """
    The single most important property: the score is ALWAYS 0-100.
    A bug that shows "112 / 100" destroys the user's trust in everything
    else on the page.
    """

    def test_a_good_resume_scores_well(self, ats_good):
        assert 70 <= ats_good["total"] <= 100

    def test_never_above_100_or_below_0(self, pdf_dir):
        from services.pdf_parser import extract_text_from_pdf
        for name in ["good.pdf", "weak.pdf"]:
            text = extract_text_from_pdf(str(pdf_dir / name))["text"]
            report = calculate_ats_score(parse_resume(text))
            assert 0 <= report["total"] <= 100

    def test_empty_resume_scores_near_zero(self):
        report = calculate_ats_score(parse_resume(""))
        assert report["total"] <= 5

    def test_no_category_exceeds_its_weight(self, ats_good):
        for category in ats_good["categories"]:
            assert 0 <= category["score"] <= category["max"]
            assert category["max"] == CATEGORY_WEIGHTS[category["key"]]


class TestScoringStructure:
    def test_the_weights_add_up_to_100(self):
        assert sum(CATEGORY_WEIGHTS.values()) == 100

    def test_every_category_is_reported(self, ats_good):
        assert len(ats_good["categories"]) == len(CATEGORY_WEIGHTS)

    def test_every_category_explains_itself(self, ats_good):
        """A score with no explanation is useless to the user."""
        for category in ats_good["categories"]:
            assert category["details"], f"{category['label']} has no details"

    def test_improvements_are_ordered_by_points_available(self, ats_good):
        points = [item["points_available"] for item in ats_good["improvements"]]
        assert points == sorted(points, reverse=True)


class TestDiscrimination:
    """A scorer that gives everything the same number is worthless."""

    def test_a_good_resume_beats_a_weak_one(self, pdf_dir):
        from services.pdf_parser import extract_text_from_pdf
        good = calculate_ats_score(parse_resume(
            extract_text_from_pdf(str(pdf_dir / "good.pdf"))["text"]))
        weak = calculate_ats_score(parse_resume(
            extract_text_from_pdf(str(pdf_dir / "weak.pdf"))["text"]))
        assert good["total"] > weak["total"] + 15

    def test_removing_contact_details_lowers_the_score(self, good_text):
        stripped = (good_text
                    .replace("priya.v99@example.com", "")
                    .replace("+91-98400-12345", "")
                    .replace("linkedin.com/in/priyav", "")
                    .replace("github.com/priyav", ""))
        before = calculate_ats_score(parse_resume(good_text))
        after = calculate_ats_score(parse_resume(stripped))
        assert after["total"] < before["total"]


class TestGrades:
    def test_bands_map_to_the_right_label(self):
        assert get_grade(95)[0] == "Excellent"
        assert get_grade(75)[0] == "Good"
        assert get_grade(60)[0] == "Average"
        assert get_grade(45)[0] == "Needs Work"
        assert get_grade(10)[0] == "Poor"

    def test_band_edges(self):
        """Off-by-one errors live exactly on these boundaries."""
        assert get_grade(85)[0] == "Excellent"
        assert get_grade(84)[0] == "Good"
        assert get_grade(70)[0] == "Good"
        assert get_grade(69)[0] == "Average"

    def test_colour_is_a_valid_bootstrap_name(self):
        for score in range(0, 101, 5):
            assert get_grade(score)[1] in ("success", "warning", "danger")


class TestScaleHelper:
    def test_proportional_award(self):
        assert _scale(0, 5, 10) == 0
        assert _scale(5, 5, 10) == 10
        assert _scale(10, 5, 10) == 10      # capped at the best value
        assert _scale(2.5, 5, 10) == 5

    def test_no_division_by_zero(self):
        assert _scale(3, 0, 10) == 0


class TestReadabilityGuard:
    def test_empty_resume_earns_no_readability_points(self):
        """
        Regression test. An empty resume used to earn 3 points for
        "lines are easy to scan", because it had no long lines -
        scoring the ABSENCE of content as good readability.
        """
        report = calculate_ats_score(parse_resume(""))
        readability = next(c for c in report["categories"]
                           if c["key"] == "readability")
        assert readability["score"] == 0
