"""
wsgi.py
=======
The entry point a REAL web server uses.

Why this file exists
--------------------
`python app.py` starts Flask's built-in development server. Flask itself
prints a warning about it, and that warning is not decoration:

    WARNING: This is a development server. Do not use it in a
    production deployment.

The development server handles one request at a time, has no protection
against slow clients, and is not hardened. On a public site it is both
slow and unsafe.

A production server (gunicorn on Linux, waitress on Windows) runs your
app instead. It needs to import the Flask object - and only that. It
must NOT run the `if __name__ == "__main__":` block at the bottom of
app.py, because that would start the development server all over again.

Importing from this tiny file gives the production server exactly what
it needs and nothing else.

How it is used
--------------
Linux / Render / Railway / Heroku:
    gunicorn wsgi:application --bind 0.0.0.0:$PORT

    "wsgi"        -> this file
    "application" -> the variable below

Windows (for testing a production setup locally):
    waitress-serve --port=8000 wsgi:application
"""

from app import app as application

# "application" is the name the WSGI standard expects. Some servers look
# for it automatically, so using it saves configuration.
#
# We also keep "app" as an alias, because plenty of tutorials and
# platform defaults expect that name instead.
app = application
