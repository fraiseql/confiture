-- The source tree the routine and view goldens are recorded against: one of
-- each shape the signature, body and view checks have split on.
CREATE SCHEMA app;

CREATE TYPE app.status AS ENUM ('new', 'done');

CREATE TABLE public.tb_thing (
    id bigint PRIMARY KEY,
    label varchar(50),
    created_at timestamptz,
    tags text[]
);

-- Live, a second overload taking integer is left behind (a stale overload).
CREATE FUNCTION public.fn_stale(p_id bigint) RETURNS bigint
LANGUAGE sql AS $$ SELECT p_id $$;

-- Live, its body is hot-patched.
CREATE FUNCTION public.fn_body(p_id integer) RETURNS integer
LANGUAGE sql AS $$ SELECT p_id + 1 $$;

-- Array arguments (#176).
CREATE FUNCTION public.fn_array(p_ids integer[], p_tags text[]) RETURNS integer
LANGUAGE sql AS $$ SELECT cardinality(p_ids) $$;

-- A schema-qualified argument type.
CREATE FUNCTION app.fn_status(p_status app.status) RETURNS text
LANGUAGE sql AS $$ SELECT p_status::text $$;

-- Types PostgreSQL spells differently from how they are written.
CREATE FUNCTION public.fn_spellings(
    p_label varchar(20), p_at timestamptz, p_local timestamp, p_code char(2), p_ratio float
) RETURNS text
LANGUAGE sql AS $$ SELECT p_label $$;

-- A VARIADIC argument is part of the signature.
CREATE FUNCTION public.fn_variadic(VARIADIC p_parts text[]) RETURNS text
LANGUAGE sql AS $$ SELECT array_to_string(p_parts, ',') $$;

-- OUT arguments are not.
CREATE FUNCTION public.fn_out(p_id integer, OUT o_id integer, OUT o_label text)
LANGUAGE sql AS $$ SELECT p_id, 'x' $$;

-- Declared, then dropped live (not deployed).
CREATE FUNCTION public.fn_gone(p_id bigint) RETURNS bigint
LANGUAGE sql AS $$ SELECT p_id $$;

-- A trigger function, read only through the PL/pgSQL compiler (#272).
CREATE FUNCTION public.fn_touch() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.created_at := now();
    RETURN NEW;
END
$$;

CREATE TRIGGER trg_touch BEFORE INSERT ON public.tb_thing
FOR EACH ROW EXECUTE FUNCTION public.fn_touch();

CREATE PROCEDURE public.pr_noop(p_n integer)
LANGUAGE sql AS $$ SELECT 1 $$;

CREATE VIEW public.v_things AS SELECT id, label FROM public.tb_thing;

CREATE VIEW app.v_status AS SELECT 'new'::app.status AS status;

CREATE MATERIALIZED VIEW public.mv_things AS SELECT id FROM public.tb_thing;
