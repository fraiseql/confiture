CREATE FUNCTION public.fn_retype(p_label varchar(20), p_id bigint) RETURNS text
LANGUAGE sql AS $$ SELECT p_label $$;

CREATE FUNCTION public.fn_when(p_at timestamp, p_n bigint) RETURNS integer
LANGUAGE sql AS $$ SELECT p_n::integer $$;

CREATE FUNCTION public.fn_body(p_id integer) RETURNS integer
LANGUAGE sql AS $$ SELECT p_id + 2 $$;

CREATE FUNCTION app.fn_array(p_ids bigint[]) RETURNS integer
LANGUAGE sql AS $$ SELECT coalesce(cardinality(p_ids), 0) $$;

CREATE FUNCTION public.fn_carried(p_id integer) RETURNS integer
LANGUAGE sql AS $$ SELECT p_id * 2 $$;
