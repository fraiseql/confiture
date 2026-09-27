-- One plain index, and one unique constraint whose backing index PostgreSQL
-- creates itself. The constraint-backed one must never count as extra drift.
CREATE INDEX ix_widget_serial ON core.tb_widget (serial);

ALTER TABLE core.tb_other ADD CONSTRAINT uq_other_label UNIQUE (label);

-- A named foreign key with every fact a foreign key holds besides its columns:
-- a target spelled with no column list (the catalog spells the key out), a
-- referential action and a deferral. A database built from it has no drift, and
-- a key re-pointed under the same name does (#501).
ALTER TABLE core.tb_other ADD CONSTRAINT fk_other_widget
    FOREIGN KEY (id) REFERENCES core.tb_widget ON DELETE CASCADE
    DEFERRABLE INITIALLY DEFERRED;
