"""
Tests for services/pdf_parser.py

These are "unit tests": each one checks ONE behaviour of ONE function,
with no web server and no database involved.
"""

import pytest

from services.pdf_parser import (
    extract_text_from_pdf, clean_text, is_pdf_file,
    InvalidPDFError, EncryptedPDFError, EmptyPDFError,
)


class TestExtractText:
    """The happy path."""

    def test_reads_a_normal_resume(self, pdf_dir):
        result = extract_text_from_pdf(str(pdf_dir / "good.pdf"))
        assert result["page_count"] == 1
        assert result["word_count"] > 50
        assert "PRIYA VENKATESAN" in result["text"]

    def test_returns_every_expected_key(self, pdf_dir):
        result = extract_text_from_pdf(str(pdf_dir / "good.pdf"))
        for key in ("text", "pages", "page_count", "word_count", "char_count"):
            assert key in result

    def test_char_count_matches_the_text(self, pdf_dir):
        result = extract_text_from_pdf(str(pdf_dir / "good.pdf"))
        assert result["char_count"] == len(result["text"])


class TestRejectsBadFiles:
    """
    Every bad input must raise OUR exception type, never a raw library
    error. app.py relies on that to show the right message.
    """

    def test_missing_file(self, pdf_dir):
        with pytest.raises(InvalidPDFError):
            extract_text_from_pdf(str(pdf_dir / "does_not_exist.pdf"))

    def test_empty_file(self, pdf_dir):
        with pytest.raises(InvalidPDFError):
            extract_text_from_pdf(str(pdf_dir / "empty.pdf"))

    def test_text_file_renamed_to_pdf(self, pdf_dir):
        """The magic-number check must catch this - the name is a lie."""
        with pytest.raises(InvalidPDFError):
            extract_text_from_pdf(str(pdf_dir / "fake.pdf"))

    def test_corrupt_pdf(self, pdf_dir):
        with pytest.raises(InvalidPDFError):
            extract_text_from_pdf(str(pdf_dir / "corrupt.pdf"))

    def test_password_protected_pdf(self, pdf_dir):
        with pytest.raises(EncryptedPDFError):
            extract_text_from_pdf(str(pdf_dir / "locked.pdf"))

    def test_scanned_pdf_with_no_text(self, pdf_dir):
        with pytest.raises(EmptyPDFError):
            extract_text_from_pdf(str(pdf_dir / "scanned.pdf"))

    def test_the_file_is_not_locked_after_a_failure(self, pdf_dir):
        """
        A regression test for a real Windows bug.

        Passing a PATH to PyMuPDF left a file handle open when the PDF
        was corrupt, so app.py could not delete it. We now read the
        bytes ourselves. If that regresses, this deletion fails.
        """
        import shutil, os
        temp = pdf_dir / "corrupt_copy.pdf"
        shutil.copy(pdf_dir / "corrupt.pdf", temp)

        with pytest.raises(InvalidPDFError):
            extract_text_from_pdf(str(temp))

        os.remove(temp)             # raises PermissionError if still locked
        assert not temp.exists()


class TestIsPdfFile:
    def test_true_for_a_real_pdf(self, pdf_dir):
        assert is_pdf_file(str(pdf_dir / "good.pdf")) is True

    def test_false_for_a_renamed_text_file(self, pdf_dir):
        assert is_pdf_file(str(pdf_dir / "fake.pdf")) is False

    def test_false_for_a_missing_file(self):
        assert is_pdf_file("nowhere/at/all.pdf") is False


class TestCleanText:
    """
    clean_text is pure - same input, same output, no files involved.
    Pure functions are the easiest thing in any codebase to test.
    """

    def test_empty_input(self):
        assert clean_text("") == ""
        assert clean_text(None) == ""

    def test_collapses_runs_of_spaces(self):
        assert clean_text("Python      Flask") == "Python Flask"

    def test_normalises_line_endings(self):
        assert "\r" not in clean_text("a\r\nb\rc")

    def test_ligatures_become_plain_letters(self):
        """A PDF stores 'fi' as one glyph; a keyword search would miss it."""
        assert clean_text("certiﬁcate") == "certificate"

    def test_bullet_characters_become_dashes(self):
        assert clean_text("• Built an app") == "- Built an app"

    def test_collapses_excess_blank_lines(self):
        assert clean_text("a\n\n\n\n\nb") == "a\n\nb"

    def test_keeps_real_content(self):
        text = "Reduced load time by 40% for 1200 users"
        assert clean_text(text) == text
