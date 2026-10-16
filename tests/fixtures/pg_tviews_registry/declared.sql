-- Every option a pg_tviews_create_or_replace() call can declare, confiture's modelled
-- keys and the ones it carries as written.
CREATE TABLE tb_label (k int PRIMARY KEY, v text);
CREATE TABLE tb_setting (k int PRIMARY KEY, v text);
CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, name text, seen_at timestamptz);
CREATE FUNCTION label_of(k bigint) RETURNS text LANGUAGE sql STABLE
AS $f$ SELECT v FROM public.tb_setting s WHERE s.k = label_of.k $f$;
SELECT tviews.pg_tviews_create_or_replace('tv_user', $q$
SELECT u.pk_user, u.id,
       jsonb_build_object('name', u.name, 'label', (SELECT v FROM tb_label LIMIT 1),
                          'setting', label_of(u.pk_user)) AS data
FROM tb_user u$q$, options => '{"logged": false, "fillfactor": 90, "uncascaded_policy": "full_refresh",
  "uncascaded_tables": {"tb_label": "warn"}, "function_reads": {"public.label_of(bigint)": ["tb_setting"]},
  "data_gin_index": true, "typename": "Member", "data_storage": "extended", "toast_tuple_target": 4096,
  "indexes": [["name"]]}');
SELECT tviews.pg_tviews_create_or_replace('tv_visit', $q$
SELECT u.pk_user AS pk_visit, u.id,
       jsonb_build_object('recent', u.seen_at > now() - interval '1 day') AS data
FROM tb_user u$q$, options => '{"time_refresh": "external"}');
