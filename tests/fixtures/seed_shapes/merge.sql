-- MERGE upserts rows whose values level 1 does not read.
MERGE INTO catalog.tb_unit AS t
USING (VALUES ('7c1f2a8e-0000-4000-8000-000000000002', 'gram')) AS s (id, identifier)
ON t.id = s.id::uuid
WHEN NOT MATCHED THEN INSERT (id, identifier) VALUES (s.id::uuid, s.identifier);
