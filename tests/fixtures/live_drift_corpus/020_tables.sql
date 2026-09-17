-- Issue #301: a table whose final shape is the CREATE plus three ALTERs.
-- A build-from-DDL tree may append an ALTER rather than edit the CREATE, so
-- what the database ends up with is the two together.
CREATE TABLE core.tb_widget (
    id BIGINT PRIMARY KEY,
    serial TEXT NOT NULL,
    legacy_drop TEXT,
    maybe_null TEXT,
    ratio INT
);

ALTER TABLE core.tb_widget DROP COLUMN legacy_drop;
ALTER TABLE core.tb_widget ALTER COLUMN maybe_null SET NOT NULL;
ALTER TABLE core.tb_widget ALTER COLUMN ratio TYPE BIGINT;

-- A second table, so a DROP TABLE mutation has something to remove that is not
-- the table every other control reads.
CREATE TABLE core.tb_other (
    id BIGINT PRIMARY KEY,
    label TEXT NOT NULL
);

-- A partitioned parent: `information_schema` reports it as BASE TABLE and
-- `parse_expected_schema` does model it, so it matches. The control that says
-- `relkind IN ('r','p')` is the right live filter (Phase 04).
CREATE TABLE core.tb_event (
    id BIGINT NOT NULL,
    occurred_at DATE NOT NULL
) PARTITION BY RANGE (occurred_at);

CREATE TABLE core.tb_event_2026 PARTITION OF core.tb_event
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
