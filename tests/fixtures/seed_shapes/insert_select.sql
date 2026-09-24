-- Values PostgreSQL computes when the row is written: not level 1's to read.
INSERT INTO prep_seed.tb_region (id, slug) SELECT gen_random_uuid(), 'x';
