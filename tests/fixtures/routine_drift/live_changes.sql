-- What happens to the live database behind the tree's back.
CREATE FUNCTION public.fn_stale(p_id integer) RETURNS bigint
LANGUAGE sql AS $$ SELECT p_id::bigint $$;

CREATE OR REPLACE FUNCTION public.fn_body(p_id integer) RETURNS integer
LANGUAGE sql AS $$ SELECT p_id + 2 $$;

CREATE OR REPLACE FUNCTION public.fn_touch() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.created_at := clock_timestamp();
    RETURN NEW;
END
$$;

DROP FUNCTION public.fn_gone(bigint);

CREATE OR REPLACE VIEW public.v_things AS
SELECT id, label FROM public.tb_thing WHERE id > 10;

DROP MATERIALIZED VIEW public.mv_things;
CREATE MATERIALIZED VIEW public.mv_things AS SELECT id FROM public.tb_thing WHERE id > 0;
