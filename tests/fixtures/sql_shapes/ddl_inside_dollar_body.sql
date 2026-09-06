CREATE OR REPLACE FUNCTION public.make_scratch() RETURNS void AS $$
BEGIN
  CREATE TABLE scratch_inside_body (id INT);
END
$$ LANGUAGE plpgsql;
