-- The statement kinds that change what a tree declares and are not
-- `AlterTableStmt`: a DROP, a RENAME and a SET SCHEMA.
--
--   ALTER TABLE t RENAME COLUMN a TO b  -> RenameStmt
--   ALTER TABLE t RENAME TO t2          -> RenameStmt
--   ALTER TABLE t SET SCHEMA s2         -> AlterObjectSchemaStmt
--   DROP TABLE t                        -> DropStmt
--
-- A tree that creates and then drops a table declares no such table; one that
-- renames a column declares the new name.
CREATE SCHEMA IF NOT EXISTS archive;

CREATE TABLE core.tb_scratch (
    id BIGINT PRIMARY KEY
);
DROP TABLE core.tb_scratch;

CREATE VIEW core.v_scratch AS SELECT 1 AS one;
DROP VIEW core.v_scratch;

CREATE FUNCTION core.fn_scratch() RETURNS INT
LANGUAGE sql IMMUTABLE AS $$ SELECT 1 $$;
DROP FUNCTION core.fn_scratch();

CREATE TABLE core.tb_renamed (
    id BIGINT PRIMARY KEY,
    old_name TEXT NOT NULL
);
ALTER TABLE core.tb_renamed RENAME COLUMN old_name TO new_name;

CREATE TABLE core.tb_moved (
    id BIGINT PRIMARY KEY
);
ALTER TABLE core.tb_moved SET SCHEMA archive;

CREATE TABLE core.tb_before_rename (
    id BIGINT PRIMARY KEY
);
ALTER TABLE core.tb_before_rename RENAME TO tb_after_rename;
