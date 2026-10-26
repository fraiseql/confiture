-- A data-modifying CTE: the rows are computed, but the table it writes is in scope.
WITH added AS (
    INSERT INTO catalog.tb_unit (id, identifier) VALUES ('7c1f2a8e-0000-4000-8000-000000000001', 'kilogram')
    RETURNING id
)
SELECT count(*) FROM added;
