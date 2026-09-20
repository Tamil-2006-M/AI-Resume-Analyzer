"""
services package
=================
This folder holds the "business logic" of the project, kept separate
from app.py so each part can be written and tested on its own:

  pdf_parser.py    - Phase 2: read text out of a PDF
  resume_parser.py - Phase 3: find name, email, skills, sections
  ai_analyzer.py   - Phase 5: send the resume to the LLM API

This __init__.py file is what makes Python treat the folder as an
importable package, so app.py can do:  from services import pdf_parser
"""
