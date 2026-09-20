"""
services/pdf_parser.py
======================
Job of this file: turn an uploaded PDF file into clean, plain text.

Nothing else. It does not know about Flask, HTTP or the database.
That separation is on purpose:

  * app.py           -> handles the web request
  * pdf_parser.py    -> handles the PDF
  * resume_parser.py -> handles understanding the text (Phase 3)

Because this module is independent you can test it straight from the
terminal without starting the website:

    python -m services.pdf_parser uploads/some_resume.pdf

Library used: PyMuPDF (https://pymupdf.readthedocs.io)
PyMuPDF is fast, needs no external programs installed, and keeps the
reading order of the text reasonably well - which matters a lot for
resumes.
"""

import os
import re
import unicodedata

# ---------------------------------------------------------------------
# Importing PyMuPDF
# ---------------------------------------------------------------------
# PyMuPDF used to be imported as "fitz". Newer versions renamed it to
# "pymupdf" and print a deprecation warning for "fitz".
# We try the new name first and fall back to the old one, so this code
# works on both new and old installations.
try:
    import pymupdf
except ImportError:                      # very old PyMuPDF versions
    import fitz as pymupdf


# ---------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------
# If a PDF gives us fewer characters than this, we treat it as "empty".
# A real resume always has more than 100 characters of text. A scanned
# resume (a photo saved as PDF) gives us almost nothing, because the
# letters are pixels, not text.
MIN_USABLE_CHARS = 100

# Safety limit. A resume is 1-3 pages; anything above this is probably
# the wrong document (a book, a report) and would slow the app down.
MAX_PAGES = 15


# ---------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------
# Why create our own exception classes instead of using a plain Exception?
# Because app.py can then catch each problem separately and show the user
# a different, helpful message for each one.

class PDFError(Exception):
    """Base class for every error this module can raise."""


class InvalidPDFError(PDFError):
    """The file is not a readable PDF (corrupted, renamed, or damaged)."""


class EncryptedPDFError(PDFError):
    """The PDF is password protected, so we cannot read the text."""


class EmptyPDFError(PDFError):
    """
    The PDF opened fine but contains (almost) no selectable text.
    The usual cause is a scanned or image-only resume.
    """


# ---------------------------------------------------------------------
# Helper 1: is this really a PDF?
# ---------------------------------------------------------------------
def is_pdf_file(file_path):
    """
    Check the first bytes of the file instead of trusting its name.

    Every genuine PDF starts with the "magic number" %PDF-  (25 50 44 46 2D).
    Someone can rename virus.exe to resume.pdf, and the browser can lie
    about the content type - but they cannot fake these bytes without the
    file actually being a PDF.

    Returns True / False.
    """
    try:
        with open(file_path, "rb") as f:          # "rb" = read in binary mode
            header = f.read(5)
        return header == b"%PDF-"
    except OSError:
        # File missing, locked by another program, or no permission.
        return False


# ---------------------------------------------------------------------
# Helper 2: clean the raw text
# ---------------------------------------------------------------------
def clean_text(raw_text):
    """
    Tidy up the messy text that comes out of a PDF.

    PDF text extraction typically produces:
      * Windows/Mac line endings mixed together
      * long runs of spaces used for visual layout
      * "ligatures" - one character that draws two letters, e.g. 'ﬁ' in
        "certiﬁcate". Left alone, a search for "certificate" would fail.
      * non-breaking spaces and fancy bullet characters
      * lots of empty lines

    A clean string makes Phase 3 (regex + keyword matching) far more
    reliable, so this small function matters more than it looks.
    """
    if not raw_text:
        return ""

    # 1. Unicode normalisation (NFKC).
    #    This converts look-alike characters into their plain equivalents:
    #    'ﬁ' -> 'fi', curly quotes -> straight quotes, full-width -> normal.
    text = unicodedata.normalize("NFKC", raw_text)

    # 2. Make all line endings the same (\r\n and \r become \n).
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. Replace non-breaking spaces and tabs with a normal space.
    text = text.replace(" ", " ").replace("\t", " ")

    # 4. Turn the common PDF bullet characters into a simple dash,
    #    so bullet points stay visible but are easy to match later.
    text = re.sub(r"[•●▪◦·]", "-", text)

    # 5. Squash 2-or-more spaces into a single space.
    text = re.sub(r"[ ]{2,}", " ", text)

    # 6. Remove spaces sitting at the start or end of every line.
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    # 7. Collapse 3-or-more blank lines into a maximum of two.
    #    We keep some blank lines because they mark section breaks.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ---------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------
def extract_text_from_pdf(file_path):
    """
    Read a PDF file and return its text plus some basic statistics.

    Parameter
    ---------
    file_path : str
        Full path to the PDF on disk.

    Returns
    -------
    dict with these keys:
        text        : str  - the cleaned resume text
        page_count  : int  - number of pages in the PDF
        word_count  : int  - number of words found
        char_count  : int  - number of characters found
        pages       : list - the cleaned text of each page separately

    Raises
    ------
    InvalidPDFError   - not a PDF / corrupted / unreadable
    EncryptedPDFError - password protected
    EmptyPDFError     - opened fine but has no usable text (scanned resume)
    """

    # --- Guard 1: does the file exist? -------------------------------
    if not os.path.exists(file_path):
        raise InvalidPDFError("The uploaded file could not be found on the server.")

    # --- Guard 2: is the file empty? ---------------------------------
    if os.path.getsize(file_path) == 0:
        raise InvalidPDFError("The uploaded file is empty (0 bytes).")

    # --- Read the whole file into memory ------------------------------
    # Why read the bytes ourselves instead of giving PyMuPDF the path?
    #
    # On Windows, if we pass a PATH and the file turns out to be corrupted,
    # PyMuPDF can leave an open handle on it. Windows then refuses to let
    # app.py delete the bad file ("file in use by another process").
    #
    # By reading the bytes here inside a "with" block, our own file handle
    # is guaranteed to be closed, and PyMuPDF only ever sees data in RAM.
    # Uploads are capped at 5 MB, so this is perfectly safe for memory.
    try:
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
    except OSError as error:
        raise InvalidPDFError(
            "The uploaded file could not be read from the server."
        ) from error

    # --- Guard 3: does it really start with %PDF- ? -------------------
    if not pdf_bytes.startswith(b"%PDF-"):
        raise InvalidPDFError(
            "This file is not a valid PDF. Please upload a real PDF resume."
        )

    # --- Open the document from memory --------------------------------
    # filetype="pdf" tells PyMuPDF how to interpret the raw bytes,
    # since there is no filename for it to guess from.
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as error:
        # PyMuPDF raises several different exception types for broken
        # files, so we catch broadly here and convert to OUR exception.
        # The original message is kept for the developer log only.
        raise InvalidPDFError(
            "The PDF appears to be corrupted and could not be opened."
        ) from error

    try:
        # --- Guard 4: password protected? -----------------------------
        if document.needs_pass:
            raise EncryptedPDFError(
                "This PDF is password protected. "
                "Please remove the password and upload it again."
            )

        # --- Guard 5: too many pages? ---------------------------------
        page_count = document.page_count
        if page_count == 0:
            raise EmptyPDFError("This PDF has no pages.")

        if page_count > MAX_PAGES:
            raise InvalidPDFError(
                f"This document has {page_count} pages. "
                f"A resume should be at most {MAX_PAGES} pages."
            )

        # --- Read the text, page by page ------------------------------
        page_texts = []
        for page_number in range(page_count):
            page = document.load_page(page_number)

            # "text" mode returns plain text in natural reading order.
            # (Other modes give HTML, JSON with coordinates, etc.)
            raw_page_text = page.get_text("text")
            page_texts.append(clean_text(raw_page_text))

    finally:
        # Always close the document, whether we succeeded or failed,
        # so the memory it used is released immediately.
        document.close()

    # --- Join the pages into one string -------------------------------
    # A blank line between pages keeps section breaks readable.
    full_text = clean_text("\n\n".join(page_texts))

    # --- Guard 6: did we actually get any text? -----------------------
    if len(full_text) < MIN_USABLE_CHARS:
        raise EmptyPDFError(
            "We could not read any text from this PDF. "
            "It looks like a scanned image or a photo saved as PDF. "
            "Please upload a PDF exported directly from Word, "
            "Google Docs or Overleaf."
        )

    # --- Build the result ---------------------------------------------
    words = full_text.split()

    return {
        "text": full_text,
        "pages": page_texts,
        "page_count": page_count,
        "word_count": len(words),
        "char_count": len(full_text),
    }


# ---------------------------------------------------------------------
# Quick manual test
# ---------------------------------------------------------------------
# This block runs ONLY when you execute the file directly:
#     python -m services.pdf_parser uploads/my_resume.pdf
# It never runs when app.py imports this module.
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m services.pdf_parser <path-to-pdf>")
        sys.exit(1)

    try:
        result = extract_text_from_pdf(sys.argv[1])
        print(f"Pages      : {result['page_count']}")
        print(f"Words      : {result['word_count']}")
        print(f"Characters : {result['char_count']}")
        print("-" * 60)
        print(result["text"][:1000])
    except PDFError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
