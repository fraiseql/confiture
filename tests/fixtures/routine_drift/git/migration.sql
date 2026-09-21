CREATE OR REPLACE FUNCTION public.fn_carried(p_id integer) RETURNS integer
LANGUAGE sql AS $$ SELECT p_id * 2 $$;
