create index idx_widget_label on widget (label);
ALTER TABLE widget ADD COLUMN rank int NOT NULL;
