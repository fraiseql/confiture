CREATE OR REPLACE FUNCTION public.run_it() RETURNS void AS $body$
BEGIN
  EXECUTE $q$CREATE TABLE inner_t (id int)$q$;
END
$body$ LANGUAGE plpgsql;
