BEGIN;
SET LOCAL search_path TO prep_seed;
SAVEPOINT before_regions;
TRUNCATE prep_seed.tb_region;
DELETE FROM prep_seed.tb_region WHERE slug = 'x';
SELECT setval('prep_seed.tb_region_seq', 1);
COMMIT;
