-- The standard units. A tenant adds its own in app.tb_custom_unit, and
-- app.v_unit reads both.
CREATE TABLE catalog.tb_unit (
    id    uuid PRIMARY KEY,
    code  text NOT NULL UNIQUE,
    label text NOT NULL
);
COMMENT ON TABLE catalog.tb_unit IS 'Units of measure every tenant starts with';
