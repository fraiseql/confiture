-- One plain index, and one unique constraint whose backing index PostgreSQL
-- creates itself. The constraint-backed one must never count as extra drift.
CREATE INDEX ix_widget_serial ON core.tb_widget (serial);

ALTER TABLE core.tb_other ADD CONSTRAINT uq_other_label UNIQUE (label);
