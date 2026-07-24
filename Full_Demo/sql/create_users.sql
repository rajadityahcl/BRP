-- =====================================================================
-- 01_create_users.sql
-- ---------------------------------------------------------------------
-- Database users and privileges for the Submission Analytics platform.
-- Run this FIRST, before the table and view scripts.
--
-- Two users, deliberately separated:
--
--   app_user       SELECT, INSERT, CREATE -- used by the Ingestion tab
--   readonly_user  SELECT only            -- used by the chat assistant
--
-- The read-only user is the real safety backstop. The assistant generates
-- SQL with a language model; even if the application-level validation were
-- bypassed, that connection physically cannot write to the database.
--
-- CHANGE THE PASSWORDS BELOW before using this anywhere real.
-- =====================================================================

-- Create the database if it does not already exist.
CREATE DATABASE IF NOT EXISTS brp_case_study
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_general_ci;

-- ---------------------------------------------------------------------
-- Read/write user: ingestion only
-- ---------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'app_user'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT, INSERT, CREATE ON brp_case_study.* TO 'app_user'@'%';

-- ---------------------------------------------------------------------
-- Read-only user: the assistant and all reporting
-- ---------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'readonly_user'@'%' IDENTIFIED BY 'CHANGE_ME_TOO';
GRANT SELECT ON brp_case_study.* TO 'readonly_user'@'%';

FLUSH PRIVILEGES;

-- ---------------------------------------------------------------------
-- Why the read-only GRANT matters more than it looks
-- ---------------------------------------------------------------------
-- The application discovers its schema at runtime from information_schema,
-- and information_schema only exposes tables the CONNECTING USER can see.
-- Without the GRANT above, schema discovery returns an empty list and every
-- question fails with "Query does not reference a known table" -- an error
-- that looks like a model problem but is actually a privileges problem.

-- Verification:
--   SHOW GRANTS FOR 'app_user'@'%';
--   SHOW GRANTS FOR 'readonly_user'@'%';
--
-- Confirm the read-only user can actually see the schema:
--   SELECT COUNT(DISTINCT table_name)
--   FROM information_schema.columns
--   WHERE table_schema = 'brp_case_study';
