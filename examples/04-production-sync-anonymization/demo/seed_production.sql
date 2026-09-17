-- Fake "production" data for the demo in run.sh.
--
-- Every PII value here is deliberately recognisable — real-looking domains,
-- a +1-617 area code, well-formed SSNs — so that verify_anonymization.sql can
-- assert their ABSENCE from staging and mean something by it. A seed of
-- 'aaa'/'bbb' placeholders would let a completely broken sync pass.
--
-- This file is NOT part of db/schema/: production data is not schema, and
-- `confiture build` must not create it.

INSERT INTO users (id, email, full_name, phone, ssn, country_code) VALUES
    (1, 'alice.martin@realmail.example.org',  'Alice Martin',  '+1-617-555-0101', '123-45-6789', 'US'),
    (2, 'bob.chen@realmail.example.org',      'Bob Chen',      '+1-617-555-0102', '234-56-7890', 'US'),
    (3, 'carla.diaz@othermail.example.net',   'Carla Diaz',    '+1-617-555-0103', '345-67-8901', 'ES');

INSERT INTO employees (id, email, full_name, phone, ssn, bank_account_number, department) VALUES
    (1, 'dana.okafor@corp.example.com', 'Dana Okafor', '+1-617-555-0201', '456-78-9012', 'GB29NWBK60161331926819', 'support'),
    -- Also a customer (users.id 1). Different seed => different pseudonym here.
    (2, 'alice.martin@realmail.example.org', 'Alice Martin', '+1-617-555-0101', '123-45-6789', 'GB94BARC10201530093459', 'engineering');

INSERT INTO products (id, sku, name, price_cents) VALUES
    (1, 'SKU-001', 'Cast iron pan', 4500),
    (2, 'SKU-002', 'Jam funnel',     900);

INSERT INTO orders (id, user_id, billing_email, customer_notes, total_cents, status) VALUES
    (1, 1, 'alice.martin@realmail.example.org', 'Call me on 617-555-0101 before delivery', 5400, 'paid'),
    (2, 2, 'bob.chen@realmail.example.org',     NULL,                                       900, 'paid'),
    (3, 1, 'alice.martin@realmail.example.org', 'Leave with neighbour at 14 Elm St',       4500, 'shipped');

INSERT INTO order_items (id, order_id, product_id, quantity) VALUES
    (1, 1, 1, 1), (2, 1, 2, 1), (3, 2, 2, 1), (4, 3, 1, 1);

INSERT INTO payments (id, order_id, cardholder_name, card_last4, stripe_customer_id, billing_zip, amount_cents) VALUES
    (1, 1, 'Alice Martin', '4242', 'cus_NffrFeUfNV2Hib', '02139', 5400),
    (2, 2, 'Bob Chen',     '1881', 'cus_OpQrStUvWxYz01', '02140',  900),
    (3, 3, 'Alice Martin', '4242', 'cus_NffrFeUfNV2Hib', '02139', 4500);

INSERT INTO user_sessions (id, user_id, ip_address, user_agent) VALUES
    (1, 1, '203.0.113.42', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'),
    (2, 2, '198.51.100.7', 'Mozilla/5.0 (X11; Linux x86_64)'),
    (3, 1, '203.0.113.42', 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)');

INSERT INTO support_tickets (id, user_id, customer_email, subject, body) VALUES
    (1, 1, 'alice.martin@realmail.example.org', 'Where is order 1?',
        'My card ending 4242 was charged but nothing arrived. Reach me on 617-555-0101.'),
    (2, 2, 'bob.chen@realmail.example.org', 'Refund please',
        'Wrong size. My SSN on file is 234-56-7890 if you need to verify.');

INSERT INTO audit_logs (id, actor_email, action, detail) VALUES
    (1, 'dana.okafor@corp.example.com', 'user.impersonate', 'impersonated users.id=1'),
    (2, 'dana.okafor@corp.example.com', 'payment.refund',   'refunded payments.id=2');
