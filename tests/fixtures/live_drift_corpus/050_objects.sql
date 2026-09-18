-- Issue #303: the objects the comparison never made. A dropped view, matview,
-- trigger or routine was exit 0 on the gate a deploy is failed by.
CREATE VIEW core.v_widget AS
    SELECT id, serial FROM core.tb_widget;

CREATE MATERIALIZED VIEW core.mv_widget AS
    SELECT count(*) AS n FROM core.tb_widget;

CREATE FUNCTION core.fn_touch() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_touch
    BEFORE UPDATE ON core.tb_widget
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch();

CREATE FUNCTION core.fn_seen(at TIMESTAMPTZ) RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE AS $$
    SELECT at IS NOT NULL;
$$;

CREATE FUNCTION core.fn_gone(widget_id BIGINT) RETURNS BIGINT
LANGUAGE sql STABLE AS $$
    SELECT widget_id;
$$;

CREATE PROCEDURE core.pr_noop()
LANGUAGE plpgsql AS $$
BEGIN
    NULL;
END;
$$;
