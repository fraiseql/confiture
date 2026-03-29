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
-- Successfully recreated views are removed; failed views remain here
-- so you can inspect them with:
--   SELECT schema_name, view_name, error_message, definition
--   FROM confiture.saved_views WHERE NOT recreated;
CREATE TABLE IF NOT EXISTS confiture.saved_views (
    id            SERIAL PRIMARY KEY,
    schema_name   TEXT NOT NULL,
    view_name     TEXT NOT NULL,
    kind          CHAR(1) NOT NULL,  -- 'v' = regular view, 'm' = materialized view
    depth         INTEGER NOT NULL,
    definition    TEXT NOT NULL,
    comment       TEXT,
    recreated     BOOLEAN NOT NULL DEFAULT FALSE,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
-- Resilient: views that fail to recreate (e.g. after a column rename) are
-- skipped with a NOTICE and their error is recorded in confiture.saved_views.
-- Successfully recreated views are removed from the table.
-- Failed views remain for inspection:
--
--   SELECT schema_name, view_name, error_message, definition
--   FROM confiture.saved_views WHERE NOT recreated;
--
-- Returns the number of views successfully recreated.
CREATE OR REPLACE FUNCTION confiture.recreate_saved_views()
RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    v_row RECORD;
    v_idx RECORD;
    v_def TEXT;
    v_count INTEGER := 0;
    v_total INTEGER := 0;
    v_failed INTEGER := 0;
    v_qualified TEXT;
    v_err_msg TEXT;
    v_err_detail TEXT;
BEGIN
    SELECT count(*) INTO v_total FROM confiture.saved_views;

    FOR v_row IN
        SELECT id, schema_name, view_name, kind, definition, comment
        FROM confiture.saved_views
        ORDER BY depth ASC, schema_name, view_name
    LOOP
        -- Strip trailing semicolons from pg_get_viewdef output
        v_def := rtrim(rtrim(v_row.definition), ';');
        v_qualified := format('%I.%I', v_row.schema_name, v_row.view_name);

        BEGIN
            IF v_row.kind = 'm' THEN
                EXECUTE format('CREATE MATERIALIZED VIEW %s AS %s WITH NO DATA',
                               v_qualified, v_def);
                EXECUTE format('REFRESH MATERIALIZED VIEW %s', v_qualified);
            ELSE
                EXECUTE format('CREATE VIEW %s AS %s', v_qualified, v_def);
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
                    EXECUTE format('COMMENT ON MATERIALIZED VIEW %s IS %L',
                                   v_qualified, v_row.comment);
                ELSE
                    EXECUTE format('COMMENT ON VIEW %s IS %L',
                                   v_qualified, v_row.comment);
                END IF;
            END IF;

            -- Mark as recreated (will be cleaned up below)
            UPDATE confiture.saved_views SET recreated = TRUE WHERE id = v_row.id;
            v_count := v_count + 1;

        EXCEPTION WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS v_err_msg = MESSAGE_TEXT,
                                    v_err_detail = PG_EXCEPTION_DETAIL;

            -- Record the error for later inspection
            UPDATE confiture.saved_views
            SET error_message = v_err_msg
            WHERE id = v_row.id;

            v_failed := v_failed + 1;

            RAISE NOTICE E'\n'
                '  ┌─ ⚠ Could not recreate view %.%\n'
                '  │  Error: %\n'
                '  │\n'
                '  │  The saved definition is preserved in confiture.saved_views.\n'
                '  │  To inspect:  SELECT definition FROM confiture.saved_views WHERE id = %;\n'
                '  │  To clean up: DELETE FROM confiture.saved_views WHERE id = %;\n'
                '  └─',
                v_row.schema_name, v_row.view_name,
                v_err_msg,
                v_row.id, v_row.id;
        END;
    END LOOP;

    -- Clean up successfully recreated views
    DELETE FROM confiture.saved_view_indexes
    WHERE saved_view_id IN (SELECT id FROM confiture.saved_views WHERE recreated);
    DELETE FROM confiture.saved_views WHERE recreated;

    -- Summary notice
    IF v_failed > 0 THEN
        RAISE NOTICE E'\n'
            '  ╔══════════════════════════════════════════════════════════════╗\n'
            '  ║  recreate_saved_views: % of % view(s) could not be         ║\n'
            '  ║  recreated. Their definitions are preserved in:            ║\n'
            '  ║                                                            ║\n'
            '  ║    SELECT schema_name, view_name, error_message,           ║\n'
            '  ║           definition                                       ║\n'
            '  ║    FROM confiture.saved_views;                             ║\n'
            '  ║                                                            ║\n'
            '  ║  You must recreate these views manually with updated SQL.  ║\n'
            '  ╚══════════════════════════════════════════════════════════════╝',
            v_failed, v_total;
    END IF;

    RETURN v_count;
END;
$$;

COMMENT ON FUNCTION confiture.save_and_drop_dependent_views(TEXT[])
    IS 'Save and drop all views depending on tables in the given schemas';

COMMENT ON FUNCTION confiture.recreate_saved_views()
    IS 'Recreate all previously saved views in correct dependency order';
