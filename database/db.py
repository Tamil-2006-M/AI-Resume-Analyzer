"""
database/db.py
==============
Job of this file: everything that touches MySQL.

app.py never writes SQL. It calls save_analysis(...) and
get_recent_analyses(...) and does not care how they work. That
separation means:

  * All SQL lives in one file, so it is easy to review and to secure.
  * Swapping MySQL for PostgreSQL later would change this file only.
  * app.py stays readable.

Three things this module is careful about
-----------------------------------------
1. THE APP STILL WORKS WITHOUT MYSQL.
   Exactly like the AI layer in Phase 5. If MySQL is not installed, not
   running, or not configured, the analysis still happens and the
   dashboard still appears - we simply do not save the history. A
   college demo must never die because a service is down.

2. EVERY QUERY IS PARAMETERISED.
   We never build SQL by joining strings together. See the big comment
   above save_analysis() for why this matters.

3. CREDENTIALS COME FROM .env.
   No password is ever written in this file.

Setting up
----------
    1. Install MySQL (or XAMPP).
    2. Run the schema:   mysql -u root -p < sql/schema.sql
    3. Fill in DB_USER and DB_PASSWORD in your .env file.
    4. Set DB_ENABLED=true
    5. Check it:         python -m database.db --check
"""

import os
import json
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Importing the driver
# ---------------------------------------------------------------------
# We import inside a try/except so that someone who has not installed
# mysql-connector-python can still run the rest of the application.
# MYSQL_AVAILABLE tells the rest of this file whether the driver exists.
try:
    import mysql.connector
    from mysql.connector import errorcode, pooling
    MYSQL_AVAILABLE = True
except ImportError:                                   # pragma: no cover
    mysql = None
    errorcode = None
    pooling = None
    MYSQL_AVAILABLE = False


# =====================================================================
# PART 1 - CONFIGURATION
# =====================================================================

def _env(name, default=""):
    """Read an environment variable, trimming spaces and stray quotes."""
    return os.getenv(name, default).strip().strip('"').strip("'")


def get_db_config():
    """
    Build the connection settings dictionary from .env.

    Returned as a dict because that is exactly what
    mysql.connector.connect(**config) expects.
    """
    return {
        "host":     _env("DB_HOST", "localhost") or "localhost",
        "port":     int(_env("DB_PORT", "3306") or 3306),
        "user":     _env("DB_USER", "root") or "root",
        "password": _env("DB_PASSWORD", ""),
        "database": _env("DB_NAME", "resume_analyzer") or "resume_analyzer",

        # utf8mb4 so emoji and Indian language scripts survive the trip.
        "charset":  "utf8mb4",
        "collation": "utf8mb4_unicode_ci",

        # Give up after 5 seconds instead of hanging the web page.
        "connection_timeout": 5,

        # We commit explicitly, so we can roll back on error.
        "autocommit": False,
    }


def is_enabled():
    """
    Should we use the database at all?

    Returns False when the driver is missing or DB_ENABLED is not "true",
    so a student without MySQL installed can still run the project.
    """
    if not MYSQL_AVAILABLE:
        return False
    return _env("DB_ENABLED", "false").lower() in ("true", "1", "yes")


# Should we store the full resume text?
#
# It is genuinely useful (you can re-analyse without the PDF), but it is
# also personal data. Making it a switch lets you turn it off, which is
# a sensible thing to be able to say in a project review.
def store_text_enabled():
    return _env("DB_STORE_RESUME_TEXT", "true").lower() in ("true", "1", "yes")


# =====================================================================
# PART 2 - ERRORS AND CONNECTIONS
# =====================================================================

class DatabaseError(Exception):
    """Any database problem, translated into one type for app.py."""


# A connection pool keeps a small set of open connections ready.
#
# Why bother? Opening a MySQL connection takes 20-50 ms - a TCP
# handshake plus authentication. Doing that on every page view is slow
# and, under load, exhausts the server's connection limit. A pool opens
# them once and hands them out.
#
# It starts as None and is built on first use ("lazy initialisation"),
# so importing this module never touches the network.
_connection_pool = None


def _build_pool():
    """Create the connection pool. Raises DatabaseError if it cannot."""
    global _connection_pool

    if not MYSQL_AVAILABLE:
        raise DatabaseError(
            "mysql-connector-python is not installed. "
            "Run: pip install -r requirements.txt")

    config = get_db_config()
    pool_size = int(_env("DB_POOL_SIZE", "5") or 5)

    try:
        _connection_pool = pooling.MySQLConnectionPool(
            pool_name="resume_analyzer_pool",
            pool_size=pool_size,
            pool_reset_session=True,
            **config,
        )
        logger.info("MySQL pool ready (%s@%s/%s, size %d)",
                    config["user"], config["host"], config["database"],
                    pool_size)
    except Exception as error:
        raise DatabaseError(_friendly_error(error)) from error

    return _connection_pool


def _friendly_error(error):
    """
    Turn a driver error into a sentence a student can act on.

    The raw messages are technical and sometimes echo the connection
    string, so we never show them to the user - only to the log.
    """
    code = getattr(error, "errno", None)

    if errorcode is not None:
        if code == errorcode.ER_ACCESS_DENIED_ERROR:
            return ("MySQL refused the username or password. "
                    "Check DB_USER and DB_PASSWORD in your .env file.")
        if code == errorcode.ER_BAD_DB_ERROR:
            return ("The database does not exist yet. "
                    "Run:  mysql -u root -p < sql/schema.sql")
        if code == errorcode.ER_NO_SUCH_TABLE:
            return ("A table is missing. "
                    "Run:  mysql -u root -p < sql/schema.sql")

    # 2003 = "Can't connect to MySQL server" (service not running).
    if code == 2003:
        return ("Could not reach the MySQL server. Is the MySQL service "
                "running? On Windows: net start MySQL80")

    # Anything else. The real message goes to the log for us; the user
    # gets a neutral sentence, because driver messages can echo back
    # connection details.
    logger.error("Unhandled MySQL error: %s", error)
    return "A database error occurred."


@contextmanager
def get_connection():
    """
    Hand out a pooled connection, and always give it back.

    Used with "with", which guarantees the connection is returned even
    if the code inside raises:

        with get_connection() as connection:
            ...

    Without this, one crash would leak a connection, and after five
    crashes the pool would be empty and the site would hang.
    """
    if _connection_pool is None:
        _build_pool()

    connection = None
    try:
        connection = _connection_pool.get_connection()
        yield connection
    except DatabaseError:
        raise
    except Exception as error:
        raise DatabaseError(_friendly_error(error)) from error
    finally:
        if connection is not None:
            # For a pooled connection, close() means "return to pool",
            # not "disconnect".
            connection.close()


def test_connection():
    """
    Check the database is reachable.

    Returns (True, message) or (False, message) instead of raising, so
    the caller can print the result without a try/except.
    """
    if not MYSQL_AVAILABLE:
        return False, "mysql-connector-python is not installed."
    if not is_enabled():
        return False, "DB_ENABLED is not set to true in your .env file."

    try:
        with get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            cursor.close()

        config = get_db_config()
        return True, (f"Connected to MySQL {version} "
                      f"at {config['host']}:{config['port']}, "
                      f"database '{config['database']}'. "
                      f"Tables: {', '.join(tables) or 'none'}")
    except DatabaseError as error:
        return False, str(error)


# =====================================================================
# PART 3 - SAVING AN ANALYSIS
# =====================================================================
#
#  *** SQL INJECTION - THE MOST IMPORTANT COMMENT IN THIS FILE ***
#
#  NEVER build a query by joining strings:
#
#      # DANGEROUS - do not do this
#      cursor.execute("SELECT * FROM users WHERE email = '" + email + "'")
#
#  If someone's email were:      ' OR '1'='1
#  the query would become:       SELECT * FROM users WHERE email = '' OR '1'='1'
#  ...which matches every row. Worse inputs can delete whole tables.
#
#  ALWAYS use placeholders and pass the values separately:
#
#      # SAFE
#      cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
#
#  The driver sends the query and the data in separate parts, so the
#  data can never be read as SQL commands. Every query below does this.
# =====================================================================


def _find_or_create_user(cursor, email, name):
    """
    Return the id of the user with this email, creating them if new.

    Note the ON DUPLICATE KEY UPDATE trick. Two people could upload at
    the same moment; a plain "SELECT then INSERT" would then crash on the
    UNIQUE constraint. This single statement handles both cases safely.

    A note on VALUES(name): MySQL 8.0.20 deprecated this form in favour
    of a row alias:

        INSERT INTO users (name, email) VALUES (%s, %s) AS new
        ON DUPLICATE KEY UPDATE name = COALESCE(new.name, name), ...

    We keep VALUES() because it works on MySQL 5.7, 8.0 and MariaDB,
    which is what students actually have installed. On MySQL 8.0.20+ it
    still runs; it only raises a deprecation warning in the server log.
    """
    cursor.execute(
        """
        INSERT INTO users (name, email)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            name = COALESCE(VALUES(name), name),
            id   = LAST_INSERT_ID(id)
        """,
        (name, email),
    )
    # LAST_INSERT_ID() returns the new id on an insert, and - because of
    # the trick above - the existing id on a duplicate.
    return cursor.lastrowid


def save_analysis(parsed, ats, ai, job_match, stored_filename,
                  original_filename, extracted_text, page_count,
                  job_description=""):
    """
    Save one complete analysis: user, resume and results.

    Returns the new analysis_results id, or None if saving was skipped
    or failed. It NEVER raises - a database problem must not cost the
    user the analysis they are already looking at.

    All three inserts happen inside ONE transaction. If the last insert
    fails, the first two are rolled back, so we never store a resume
    with no results attached to it. That is what ACID means in practice.
    """
    if not is_enabled():
        return None

    # No email means no way to identify the person. We still save the
    # row, under a clearly fake address, so the history is not lost.
    email = (parsed["contact"].get("email")
             or "anonymous@resume-analyzer.local")
    name = parsed["contact"].get("name")

    text_to_store = extracted_text if store_text_enabled() else None

    try:
        with get_connection() as connection:
            cursor = connection.cursor()

            try:
                # ---- 1. the user ----
                user_id = _find_or_create_user(cursor, email, name)

                # ---- 2. the resume ----
                cursor.execute(
                    """
                    INSERT INTO resumes
                        (user_id, file_name, original_name, extracted_text,
                         ats_score, page_count, word_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        stored_filename,
                        original_filename,
                        text_to_store,
                        ats["total"] if ats else None,
                        page_count,
                        parsed["stats"]["word_count"],
                    ),
                )
                resume_id = cursor.lastrowid

                # ---- 3. the analysis ----
                # json.dumps turns a Python list into a JSON string,
                # which is what the JSON column type expects.
                cursor.execute(
                    """
                    INSERT INTO analysis_results
                        (resume_id, job_match_score, job_description,
                         skills, missing_skills, suggestions,
                         sections_missing, ai_source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        resume_id,
                        job_match["match_percent"] if job_match else None,
                        job_description or None,
                        json.dumps(parsed["skills"]["technical"]),
                        json.dumps(job_match["missing_skills"]
                                   if job_match
                                   else (ai["missing_skills"] if ai else [])),
                        json.dumps(ai["suggestions"] if ai else []),
                        json.dumps([s["label"]
                                    for s in parsed["sections"]["missing"]]),
                        ai["source"] if ai else None,
                    ),
                )
                analysis_id = cursor.lastrowid

                # Nothing is permanent until commit() is called.
                connection.commit()

                logger.info("Saved analysis #%s (user %s, resume %s)",
                            analysis_id, user_id, resume_id)
                return analysis_id

            except Exception:
                # Undo everything this transaction did.
                connection.rollback()
                raise
            finally:
                cursor.close()

    except DatabaseError as error:
        logger.warning("Could not save analysis: %s", error)
        return None
    except Exception as error:
        logger.exception("Unexpected error saving analysis: %s", error)
        return None


# =====================================================================
# PART 4 - READING THE HISTORY BACK
# =====================================================================

def get_recent_analyses(limit=20):
    """
    Return the most recent analyses for the history page.

    Note how the limit is handled: it is forced to an int and clamped to
    a sane range. LIMIT cannot take a placeholder in all MySQL versions,
    so this value ends up inside the query string - which means it MUST
    be proven to be a number first. int() does exactly that: anything
    that is not a number raises instead of reaching the database.
    """
    if not is_enabled():
        return []

    # int() proves the value is a number. If a future version of this app
    # ever passes ?limit= straight from the URL, "25; DROP TABLE users"
    # raises here and never reaches MySQL. We then fall back to a default
    # rather than letting the exception break the page.
    try:
        safe_limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid limit %r, using 20", limit)
        safe_limit = 20

    try:
        with get_connection() as connection:
            # dictionary=True gives rows as {"column": value} instead of
            # tuples, which is far nicer inside a Jinja template.
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT analysis_id, resume_id, user_name, user_email,
                       file_name, ats_score, job_match_score, ai_source,
                       created_at
                FROM recent_analyses
                ORDER BY created_at DESC
                LIMIT {safe_limit}
                """
            )
            rows = cursor.fetchall()
            cursor.close()
            return rows

    except DatabaseError as error:
        logger.warning("Could not read history: %s", error)
        return []
    except Exception as error:
        logger.exception("Unexpected error reading history: %s", error)
        return []


def get_user_score_history(email, limit=12):
    """
    Return this candidate's past ATS scores, oldest first.

    Used by the "your score over time" line chart on the result page.
    Oldest first because a time axis reads left to right.

    Returns [] when the database is off, the email is unknown, or the
    person has only ever uploaded once - the template then hides the
    chart, because a single point is not a trend.
    """
    if not is_enabled() or not email:
        return []

    try:
        safe_limit = max(2, min(int(limit), 50))
    except (TypeError, ValueError):
        safe_limit = 12

    try:
        with get_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT r.ats_score, r.uploaded_at, r.original_name
                FROM resumes r
                JOIN users u ON u.id = r.user_id
                WHERE u.email = %s
                  AND r.ats_score IS NOT NULL
                ORDER BY r.uploaded_at ASC
                LIMIT {safe_limit}
                """,
                (email,),
            )
            rows = cursor.fetchall()
            cursor.close()
            return rows

    except DatabaseError as error:
        logger.warning("Could not read score history: %s", error)
        return []
    except Exception as error:
        logger.exception("Unexpected error reading score history: %s", error)
        return []


def get_score_distribution():
    """
    Count how many resumes fall into each ATS grade band.

    Used by the histogram on the history page.

    The binning is done by MySQL with CASE + GROUP BY rather than in
    Python. Two reasons, both worth knowing:
      * the database only sends back 5 rows instead of every score
      * grouping is exactly what a database is built to do quickly

    The bands match get_grade() in services/ats_scorer.py - if you change
    them there, change them here too.
    """
    if not is_enabled():
        return []

    bands = [
        ("Poor (0-39)", 0, 39),
        ("Needs Work (40-54)", 40, 54),
        ("Average (55-69)", 55, 69),
        ("Good (70-84)", 70, 84),
        ("Excellent (85-100)", 85, 100),
    ]

    try:
        with get_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    CASE
                        WHEN ats_score >= 85 THEN 'Excellent (85-100)'
                        WHEN ats_score >= 70 THEN 'Good (70-84)'
                        WHEN ats_score >= 55 THEN 'Average (55-69)'
                        WHEN ats_score >= 40 THEN 'Needs Work (40-54)'
                        ELSE 'Poor (0-39)'
                    END AS band,
                    COUNT(*) AS total
                FROM resumes
                WHERE ats_score IS NOT NULL
                GROUP BY band
                """
            )
            counts = {row["band"]: row["total"] for row in cursor.fetchall()}
            cursor.close()

        # SQL only returns bands that have rows. The chart needs all five
        # in order, so we fill the gaps with zero here.
        return [{"band": label, "total": counts.get(label, 0)}
                for label, _low, _high in bands]

    except DatabaseError as error:
        logger.warning("Could not read score distribution: %s", error)
        return []
    except Exception as error:
        logger.exception("Unexpected error reading distribution: %s", error)
        return []


def get_statistics():
    """
    A few totals for the top of the history page.

    One query with several COUNT/AVG expressions is much cheaper than
    four separate round trips to the database.
    """
    if not is_enabled():
        return None

    try:
        with get_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM users)            AS total_users,
                    (SELECT COUNT(*) FROM resumes)          AS total_resumes,
                    (SELECT COUNT(*) FROM analysis_results) AS total_analyses,
                    (SELECT ROUND(AVG(ats_score))
                       FROM resumes WHERE ats_score IS NOT NULL)
                                                            AS average_ats
                """
            )
            stats = cursor.fetchone()
            cursor.close()
            return stats

    except DatabaseError as error:
        logger.warning("Could not read statistics: %s", error)
        return None
    except Exception as error:
        logger.exception("Unexpected error reading statistics: %s", error)
        return None


# =====================================================================
# PART 5 - COMMAND LINE HELPERS
# =====================================================================

def _split_sql_statements(script):
    """
    Split a .sql file into individual statements.

    Two steps:
      1. Drop "-- comment" lines, because a comment could contain a
         semicolon and confuse the split.
      2. Split on ";" and throw away whatever is left blank.

    This is deliberately simple. It is enough for our schema, which has
    no stored procedures or triggers - those contain semicolons INSIDE
    the statement and would need a real SQL parser.
    """
    lines = []
    for line in script.split("\n"):
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)

    cleaned = "\n".join(lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def init_database():
    """
    Run sql/schema.sql from Python.

    Handy if you do not have the mysql command line tool on your PATH.
    We connect WITHOUT a database name, because schema.sql creates it.
    """
    if not MYSQL_AVAILABLE:
        return False, "mysql-connector-python is not installed."

    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "sql", "schema.sql")

    if not os.path.exists(schema_path):
        return False, f"Could not find {schema_path}"

    with open(schema_path, "r", encoding="utf-8") as f:
        script = f.read()

    config = get_db_config()
    config.pop("database")          # the script creates it itself
    config["autocommit"] = True

    try:
        connection = mysql.connector.connect(**config)
        cursor = connection.cursor()

        # Run the statements one at a time.
        #
        # Older tutorials use cursor.execute(script, multi=True) for this.
        # That parameter was deprecated in mysql-connector-python 8.0.32
        # and REMOVED in 9.0, so on a current driver it raises
        # "TypeError: execute() got an unexpected keyword argument 'multi'".
        # Splitting the file ourselves works on every version.
        for statement in _split_sql_statements(script):
            cursor.execute(statement)

            # SELECT and SHOW produce rows. If we do not read them, the
            # next execute() fails with "Unread result found".
            if cursor.with_rows:
                cursor.fetchall()

        cursor.close()
        connection.close()
        return True, "Schema created. Tables are ready."

    except Exception as error:
        return False, _friendly_error(error)


def update_env_file(updates):
    """
    Change some KEY=VALUE lines in the .env file, leaving the rest alone.

    Used by the --setup command so the student does not have to open the
    file in an editor. We rewrite only the keys we were given; every
    other line, comment and blank line is preserved exactly.
    """
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

    if not os.path.exists(env_path):
        return False, f"No .env file found at {env_path}"

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    remaining = dict(updates)
    output = []

    for line in lines:
        stripped = line.strip()
        # Only touch real settings, never comments or blank lines.
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}\n")
                continue
        output.append(line)

    # Any key that was not already in the file gets appended.
    for key, value in remaining.items():
        output.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(output)

    return True, f"Updated {', '.join(updates)} in .env"


def interactive_setup():
    """
    One command that does the whole database setup.

    Asks for the MySQL password (hidden as you type), tests it, creates
    the tables and saves the settings to .env. This exists because the
    manual route trips people up on Windows: PowerShell has no "<"
    redirection operator, so the usual
        mysql -u root -p < sql/schema.sql
    fails with "The '<' operator is reserved for future use."
    """
    import getpass

    print("=" * 62)
    print("  AI Resume Analyzer - database setup")
    print("=" * 62)

    config = get_db_config()
    print(f"\n  Server : {config['host']}:{config['port']}")
    print(f"  User   : {config['user']}")
    print(f"  Database will be: {config['database']}\n")

    # getpass does not echo the password to the screen, so it cannot be
    # read over your shoulder or left behind in the terminal scrollback.
    password = getpass.getpass(f"  Password for MySQL user "
                               f"'{config['user']}': ")

    os.environ["DB_PASSWORD"] = password
    os.environ["DB_ENABLED"] = "true"

    # Force the pool to be rebuilt with the new password.
    global _connection_pool
    _connection_pool = None

    print("\n  [1/3] Creating the database and tables...")
    ok, message = init_database()
    if not ok:
        print(f"        FAILED: {message}")
        return False
    print(f"        {message}")

    print("  [2/3] Testing the connection...")
    ok, message = test_connection()
    if not ok:
        print(f"        FAILED: {message}")
        return False
    print(f"        {message}")

    print("  [3/3] Saving settings to .env...")
    ok, message = update_env_file({
        "DB_ENABLED": "true",
        "DB_PASSWORD": password,
    })
    print(f"        {message}")
    if not ok:
        print("        Add DB_ENABLED=true and your password to .env "
              "by hand.")
        return False

    print("\n" + "=" * 62)
    print("  Done. Restart the app and open http://127.0.0.1:5000/history")
    print("=" * 62)
    return True


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s: %(message)s")

    command = sys.argv[1] if len(sys.argv) > 1 else "--check"

    if command == "--setup":
        sys.exit(0 if interactive_setup() else 1)

    elif command == "--init":
        print("Creating the database and tables...")
        ok, message = init_database()
        print(("OK: " if ok else "FAILED: ") + message)
        sys.exit(0 if ok else 1)

    elif command == "--check":
        config = get_db_config()
        print("Settings read from .env")
        print(f"  DB_ENABLED : {is_enabled()}")
        print(f"  DB_HOST    : {config['host']}:{config['port']}")
        print(f"  DB_USER    : {config['user']}")
        print(f"  DB_PASSWORD: {'(set)' if config['password'] else '(empty)'}")
        print(f"  DB_NAME    : {config['database']}")
        print()

        ok, message = test_connection()
        print(("OK: " if ok else "FAILED: ") + message)

        if ok:
            stats = get_statistics()
            if stats:
                print(f"\n  Users    : {stats['total_users']}")
                print(f"  Resumes  : {stats['total_resumes']}")
                print(f"  Analyses : {stats['total_analyses']}")
                print(f"  Avg ATS  : {stats['average_ats']}")
        sys.exit(0 if ok else 1)

    else:
        print("Usage: python -m database.db [--setup | --check | --init]")
        print()
        print("  --setup   ask for the password, create the tables and")
        print("            save the settings to .env  (start here)")
        print("  --check   show the current settings and test the connection")
        print("  --init    run sql/schema.sql using the settings already")
        print("            in .env")
        sys.exit(1)
