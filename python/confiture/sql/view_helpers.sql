-- Confiture View Dependency Helpers
--
-- Reusable PL/pgSQL functions for managing view dependencies during
-- ALTER COLUMN TYPE migrations. Install once, use from any migration.
--
-- Usage in a .up.sql migration:
--
--   SELECT confiture.save_and_drop_dependent_views(ARRAY['public', 'catalog']);
--   ALTER TABLE catalog.tb_machine ALTER COLUMN pk_machine TYPE BIGINT;
--   SELECT confiture.recreate_saved_views();

CREATE SCHEMA IF NOT EXISTS confiture;

-- Table to hold saved view definitions between save and recreate calls.
CREATE TABLE IF NOT EXISTS confiture.saved_views (
    id          SERIAL PRIMARY KEY,
    schema_name TEXT NOT NULL,
    view_name   TEXT NOT NULL,
    kind        CHAR(1) NOT NULL,  -- 'v' = regular view, 'm' = materialized view
    depth       INTEGER NOT NULL,
    definition  TEXT NOT NULL,
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS confiture.saved_view_indexes (
    id              SERIAL PRIMARY KEY,
    saved_view_id   INTEGER NOT NULL REFERENCES confiture.saved_views(id) ON DELETE CASCADE,
    index_name      TEXT NOT NULL,
    index_def       TEXT NOT NULL
);

-- save_and_drop_dependent_views(p_schemas TEXT[])
--
-- Discovers all views (regular and materialized) that depend on tables
-- in the given schemas, saves their definitions/indexes/comments, and
-- drops them in reverse dependency order.
--
-- Returns the number of views dropped.
CREATE OR REPLACE FUNCTION confiture.save_and_drop_dependent_views(
    p_schemas TEXT[] DEFAULT NULL
) RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    v_row RECORD;
    v_def TEXT;
    v_comment TEXT;
    v_saved_id INTEGER;
    v_idx RECORD;
    v_count INTEGER := 0;
    v_schemas TEXT[];
BEGIN
    -- If no schemas specified, scan all user schemas
    IF p_schemas IS NULL THEN
        SELECT array_agg(nspname ORDER BY nspname)
        INTO v_schemas
        FROM pg_namespace
        WHERE nspname NOT LIKE 'pg_%'
          AND nspname != 'information_schema';
    ELSE
        v_schemas := p_schemas;
    END IF;

    -- Clear any previously saved views
    DELETE FROM confiture.saved_view_indexes;
    DELETE FROM confiture.saved_views;

    -- Discover and save all dependent views
    FOR v_row IN
        WITH RECURSIVE
        base_tables AS (
            SELECT c.oid
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ANY(v_schemas)
              AND c.relkind IN ('r', 'p')
        ),
        view_deps AS (
            SELECT DISTINCT
                dep_view.oid,
                dep_ns.nspname AS schema_name,
                dep_view.relname AS view_name,
                dep_view.relkind::text AS kind,
                0 AS depth
            FROM pg_depend d
            JOIN pg_rewrite rw ON d.objid = rw.oid
            JOIN pg_class dep_view ON rw.ev_class = dep_view.oid
            JOIN pg_namespace dep_ns ON dep_view.relnamespace = dep_ns.oid
            WHERE d.refobjid IN (SELECT oid FROM base_tables)
              AND dep_view.relkind IN ('v', 'm')
              AND d.deptype = 'n'
              AND dep_view.oid != d.refobjid

            UNION

            SELECT DISTINCT
                dep_view.oid,
                dep_ns.nspname,
                dep_view.relname,
                dep_view.relkind::text,
                vd.depth + 1
            FROM view_deps vd
            JOIN pg_depend d ON d.refobjid = vd.oid
            JOIN pg_rewrite rw ON d.objid = rw.oid
            JOIN pg_class dep_view ON rw.ev_class = dep_view.oid
            JOIN pg_namespace dep_ns ON dep_view.relnamespace = dep_ns.oid
            WHERE dep_view.relkind IN ('v', 'm')
              AND dep_view.oid != vd.oid
              AND d.deptype = 'n'
        )
        SELECT DISTINCT ON (oid) oid, schema_name, view_name, kind, depth
        FROM view_deps
        ORDER BY oid, depth DESC
    LOOP
        -- Get view definition
        v_def := pg_get_viewdef(v_row.oid, true);

        -- Get comment
        v_comment := obj_description(v_row.oid);

        -- Save the view
        INSERT INTO confiture.saved_views (schema_name, view_name, kind, depth, definition, comment)
        VALUES (v_row.schema_name, v_row.view_name, v_row.kind, v_row.depth, v_def, v_comment)
        RETURNING id INTO v_saved_id;

        -- Save indexes for materialized views
        IF v_row.kind = 'm' THEN
            FOR v_idx IN
                SELECT pi.indexname, pg_get_indexdef(i.indexrelid) AS index_def
                FROM pg_indexes pi
                JOIN pg_index i ON i.indexrelid = (
                    SELECT c.oid FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = pi.schemaname AND c.relname = pi.indexname
                )
                WHERE pi.schemaname = v_row.schema_name AND pi.tablename = v_row.view_name
            LOOP
                INSERT INTO confiture.saved_view_indexes (saved_view_id, index_name, index_def)
                VALUES (v_saved_id, v_idx.indexname, v_idx.index_def);
            END LOOP;
        END IF;
    END LOOP;

    -- Drop views in reverse depth order (deepest first)
    FOR v_row IN
        SELECT schema_name, view_name, kind
        FROM confiture.saved_views
        ORDER BY depth DESC, schema_name, view_name
    LOOP
        IF v_row.kind = 'm' THEN
            EXECUTE format('DROP MATERIALIZED VIEW IF EXISTS %I.%I CASCADE',
                           v_row.schema_name, v_row.view_name);
        ELSE
            EXECUTE format('DROP VIEW IF EXISTS %I.%I CASCADE',
                           v_row.schema_name, v_row.view_name);
        END IF;
        v_count := v_count + 1;
    END LOOP;

    RETURN v_count;
END;
$$;

-- recreate_saved_views()
--
-- Recreates all views previously saved by save_and_drop_dependent_views(),
-- in forward dependency order (shallowest first). Restores indexes on
-- materialized views and comments on all views.
--
-- Returns the number of views recreated.
CREATE OR REPLACE FUNCTION confiture.recreate_saved_views()
RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    v_row RECORD;
    v_idx RECORD;
    v_def TEXT;
    v_count INTEGER := 0;
BEGIN
    FOR v_row IN
        SELECT id, schema_name, view_name, kind, definition, comment
        FROM confiture.saved_views
        ORDER BY depth ASC, schema_name, view_name
    LOOP
        -- Strip trailing semicolons from pg_get_viewdef output
        v_def := rtrim(rtrim(v_row.definition), ';');

        IF v_row.kind = 'm' THEN
            EXECUTE format('CREATE MATERIALIZED VIEW %I.%I AS %s WITH NO DATA',
                           v_row.schema_name, v_row.view_name, v_def);
            EXECUTE format('REFRESH MATERIALIZED VIEW %I.%I',
                           v_row.schema_name, v_row.view_name);
        ELSE
            EXECUTE format('CREATE VIEW %I.%I AS %s',
                           v_row.schema_name, v_row.view_name, v_def);
        END IF;

        -- Restore indexes for materialized views
        FOR v_idx IN
            SELECT index_name, index_def
            FROM confiture.saved_view_indexes
            WHERE saved_view_id = v_row.id
        LOOP
            EXECUTE v_idx.index_def;
        END LOOP;

        -- Restore comment
        IF v_row.comment IS NOT NULL THEN
            IF v_row.kind = 'm' THEN
                EXECUTE format('COMMENT ON MATERIALIZED VIEW %I.%I IS %L',
                               v_row.schema_name, v_row.view_name, v_row.comment);
            ELSE
                EXECUTE format('COMMENT ON VIEW %I.%I IS %L',
                               v_row.schema_name, v_row.view_name, v_row.comment);
            END IF;
        END IF;

        v_count := v_count + 1;
    END LOOP;

    -- Clean up saved data
    DELETE FROM confiture.saved_view_indexes;
    DELETE FROM confiture.saved_views;

    RETURN v_count;
END;
$$;

COMMENT ON FUNCTION confiture.save_and_drop_dependent_views(TEXT[])
    IS 'Save and drop all views depending on tables in the given schemas';

COMMENT ON FUNCTION confiture.recreate_saved_views()
    IS 'Recreate all previously saved views in correct dependency order';
