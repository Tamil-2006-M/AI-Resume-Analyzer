-- ====================================================================
--  AI Resume Analyzer - MySQL schema
-- ====================================================================
--  Run this ONCE to create the database and its tables.
--
--  From the Windows command line:
--      mysql -u root -p < sql/schema.sql
--
--  Or from inside the MySQL shell:
--      SOURCE E:/AI Resume Analyzer/sql/schema.sql;
--
--  Or paste the whole file into MySQL Workbench and press the lightning
--  bolt button.
-- ====================================================================


-- --------------------------------------------------------------------
--  1. THE DATABASE
-- --------------------------------------------------------------------
--  IF NOT EXISTS means running this file twice is safe - it will not
--  destroy data you already have.
--
--  utf8mb4 is the character set. Use it, never plain "utf8":
--    * utf8mb4 stores ALL Unicode, including emoji and every Indian
--      language script.
--    * MySQL's old "utf8" is really 3-byte only and silently breaks on
--      4-byte characters. A resume with an emoji would fail to save.
CREATE DATABASE IF NOT EXISTS resume_analyzer
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE resume_analyzer;


-- --------------------------------------------------------------------
--  2. USERS
-- --------------------------------------------------------------------
--  One row per person who uploads a resume.
--
--  This project has no login system, so we identify a user by the email
--  address found inside their resume. If a resume has no email we store
--  a placeholder instead (see database/db.py).
CREATE TABLE IF NOT EXISTS users (
    -- INT UNSIGNED: 0 to 4.2 billion. Never negative, so UNSIGNED
    -- doubles the usable range for free.
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,

    name        VARCHAR(120) DEFAULT NULL,

    -- UNIQUE stops the same person being stored twice. It also creates
    -- an index automatically, which makes "find user by email" fast.
    email       VARCHAR(191) NOT NULL UNIQUE,

    -- Filled in by MySQL itself when the row is inserted.
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
--  Why VARCHAR(191) and not 255?
--  On older MySQL versions an indexed utf8mb4 column can be at most 767
--  bytes, and 191 x 4 bytes = 764. Using 191 keeps the UNIQUE index
--  working on every MySQL version you are likely to meet.
--
--  Why ENGINE=InnoDB?
--  InnoDB supports transactions and foreign keys. The older MyISAM
--  engine supports neither, so a half-finished save could leave a
--  resume row with no analysis row attached to it.


-- --------------------------------------------------------------------
--  3. RESUMES
-- --------------------------------------------------------------------
--  One row per uploaded PDF.
CREATE TABLE IF NOT EXISTS resumes (
    id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id         INT UNSIGNED NOT NULL,

    -- The name the user's file was saved as inside uploads/
    file_name       VARCHAR(255) NOT NULL,

    -- The original name they chose, kept so we can show it back to them.
    original_name   VARCHAR(255) DEFAULT NULL,

    -- LONGTEXT holds up to 4 GB. A resume is a few kilobytes, but TEXT
    -- (64 KB) could truncate an unusually long CV, and a truncated
    -- resume would silently corrupt any later re-analysis.
    extracted_text  LONGTEXT,

    -- The ATS score out of 100. TINYINT UNSIGNED covers 0-255.
    ats_score       TINYINT UNSIGNED DEFAULT NULL,

    page_count      SMALLINT UNSIGNED DEFAULT NULL,
    word_count      MEDIUMINT UNSIGNED DEFAULT NULL,

    uploaded_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    -- An index on the columns we filter and sort by. Without it, MySQL
    -- reads every row to answer "show me this user's recent resumes".
    INDEX idx_resumes_user (user_id),
    INDEX idx_resumes_uploaded (uploaded_at),

    -- A FOREIGN KEY guarantees user_id always points at a real user.
    -- ON DELETE CASCADE: deleting a user deletes their resumes too, so
    -- we can never leave orphan rows behind.
    CONSTRAINT fk_resumes_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------------------
--  4. ANALYSIS RESULTS
-- --------------------------------------------------------------------
--  One row per analysis of a resume.
--
--  Kept separate from "resumes" because the same PDF can be analysed
--  again against a different job description. One resume, many results.
CREATE TABLE IF NOT EXISTS analysis_results (
    id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
    resume_id         INT UNSIGNED NOT NULL,

    -- NULL when the user did not paste a job description.
    job_match_score   TINYINT UNSIGNED DEFAULT NULL,
    job_description   TEXT DEFAULT NULL,

    -- These four hold JSON.
    --
    -- The JSON data type (MySQL 5.7+) validates the value on insert and
    -- lets you query inside it later, for example:
    --     SELECT * FROM analysis_results
    --     WHERE JSON_CONTAINS(skills, '"Python"');
    --
    -- We store lists as JSON instead of creating a separate skills table
    -- because we only ever read them back as a whole list. A normalised
    -- design would be better if we needed "how many resumes mention
    -- Docker?" - that is a good thing to mention as a possible
    -- improvement in your project report.
    skills            JSON DEFAULT NULL,
    missing_skills    JSON DEFAULT NULL,
    suggestions       JSON DEFAULT NULL,
    sections_missing  JSON DEFAULT NULL,

    -- "ai" or "offline", so we know whether a real model was used.
    ai_source         VARCHAR(20) DEFAULT NULL,

    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    INDEX idx_results_resume (resume_id),
    INDEX idx_results_created (created_at),

    CONSTRAINT fk_results_resume
        FOREIGN KEY (resume_id) REFERENCES resumes(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------------------
--  5. A CONVENIENCE VIEW
-- --------------------------------------------------------------------
--  A VIEW is a saved SELECT. It stores no data of its own - it just
--  saves you writing the same three-table JOIN every time.
--
--      SELECT * FROM recent_analyses LIMIT 10;
CREATE OR REPLACE VIEW recent_analyses AS
SELECT
    ar.id                AS analysis_id,
    r.id                 AS resume_id,
    u.id                 AS user_id,
    u.name               AS user_name,
    u.email              AS user_email,
    r.original_name      AS file_name,
    r.ats_score,
    ar.job_match_score,
    ar.ai_source,
    ar.created_at
FROM analysis_results ar
JOIN resumes  r ON r.id = ar.resume_id
JOIN users    u ON u.id = r.user_id
ORDER BY ar.created_at DESC;


-- --------------------------------------------------------------------
--  6. CHECK IT WORKED
-- --------------------------------------------------------------------
--  These two lines print confirmation when you run the file.
SELECT 'Database and tables created successfully.' AS status;
SHOW TABLES;
