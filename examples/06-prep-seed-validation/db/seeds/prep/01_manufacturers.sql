-- Seed data for prep_seed.tb_manufacturer
-- Using UUIDs makes it easy to reference in other seed files
INSERT INTO prep_seed.tb_manufacturer (id, name, country_code) VALUES
    ('550e8400-e29b-41d4-a716-446655440000', 'Acme Corporation', 'US'),
    ('550e8400-e29b-41d4-a716-446655440001', 'Widget Inc', 'CA'),
    ('550e8400-e29b-41d4-a716-446655440002', 'Tech Solutions GmbH', 'DE'),
    ('550e8400-e29b-41d4-a716-446655440003', 'Global Industries Ltd', 'UK');
