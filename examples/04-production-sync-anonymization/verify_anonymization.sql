-- Verification: prove the anonymization actually happened.
--
-- Run against the SYNC TARGET (staging), after `confiture sync --anonymize`:
--
--     psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f verify_anonymization.sql
--
-- Every check RAISEs on violation, so with ON_ERROR_STOP=1 the script's exit
-- code is the verdict and this can sit in CI unattended.
--
-- Why this file exists at all: `confiture sync` exiting 0 tells you rows moved.
-- It does not tell you they were masked — a rule naming a column that does not
-- exist, a table absent from the config, a `--anonymize` someone dropped from
-- the command line, all leave you with a green sync and plaintext PII in
-- staging. The masking is the claim, so the masking is what gets asserted.
--
-- Confiture ships no PII-audit command. This file is the audit.

\set ON_ERROR_STOP on

-- =============================================================================
-- 1. No source PII survived
--
-- The strongest check available, and the reason demo/seed_production.sql uses
-- recognisable values: these exact strings existed in production, so finding
-- one in staging is proof of a leak rather than a heuristic about it.
-- =============================================================================

DO $$
DECLARE
    leaked RECORD;
    n      INTEGER := 0;
BEGIN
    FOR leaked IN
        SELECT 'users.email'            AS where_, email  AS value FROM users            WHERE email  LIKE '%realmail.example.org' OR email LIKE '%othermail.example.net'
        UNION ALL
        SELECT 'users.full_name',       full_name        FROM users            WHERE full_name IN ('Alice Martin', 'Bob Chen', 'Carla Diaz')
        UNION ALL
        SELECT 'users.phone',           phone            FROM users            WHERE phone LIKE '+1-617-%'
        UNION ALL
        SELECT 'users.ssn',             ssn              FROM users            WHERE ssn ~ '^\d{3}-\d{2}-\d{4}$'
        UNION ALL
        SELECT 'employees.email',       email            FROM employees        WHERE email LIKE '%corp.example.com' OR email LIKE '%realmail.example.org'
        UNION ALL
        SELECT 'employees.ssn',         ssn              FROM employees        WHERE ssn ~ '^\d{3}-\d{2}-\d{4}$'
        UNION ALL
        SELECT 'employees.bank_account_number', bank_account_number FROM employees WHERE bank_account_number LIKE 'GB%'
        UNION ALL
        SELECT 'orders.billing_email',  billing_email    FROM orders           WHERE billing_email LIKE '%realmail.example.org'
        UNION ALL
        SELECT 'orders.customer_notes', customer_notes   FROM orders           WHERE customer_notes IS NOT NULL AND customer_notes <> '[REDACTED]'
        UNION ALL
        SELECT 'payments.cardholder_name', cardholder_name FROM payments       WHERE cardholder_name IN ('Alice Martin', 'Bob Chen')
        UNION ALL
        SELECT 'payments.card_last4',   card_last4       FROM payments         WHERE card_last4 ~ '^\d{4}$'
        UNION ALL
        SELECT 'payments.stripe_customer_id', stripe_customer_id FROM payments WHERE stripe_customer_id LIKE 'cus_%'
        UNION ALL
        SELECT 'user_sessions.ip_address', ip_address    FROM user_sessions    WHERE ip_address ~ '^\d+\.\d+\.\d+\.\d+$'
        UNION ALL
        SELECT 'support_tickets.customer_email', customer_email FROM support_tickets WHERE customer_email LIKE '%realmail.example.org'
        UNION ALL
        SELECT 'support_tickets.body',  body             FROM support_tickets  WHERE body <> '[REDACTED]'
    LOOP
        n := n + 1;
        RAISE WARNING 'PII LEAK: % still holds %', leaked.where_, leaked.value;
    END LOOP;

    IF n > 0 THEN
        RAISE EXCEPTION 'anonymization failed: % column value(s) reached staging unmasked', n;
    END IF;
    RAISE NOTICE '1. no source PII survived';
END $$;

-- =============================================================================
-- 2. The masked values have the shape each strategy promises
--
-- The mirror of check 1. A column emptied to NULL, or dropped from the sync
-- entirely, also contains no PII — and is useless. This asserts the data is
-- still there and still the right kind of thing.
-- =============================================================================

DO $$
DECLARE
    bad INTEGER;
BEGIN
    -- email -> user_<8 hex>@example.com
    SELECT count(*) INTO bad FROM users WHERE email !~ '^user_[0-9a-f]{8}@example\.com$';
    IF bad > 0 THEN RAISE EXCEPTION 'users.email: % row(s) are not email-strategy output', bad; END IF;

    SELECT count(*) INTO bad FROM orders
     WHERE billing_email IS NOT NULL AND billing_email !~ '^user_[0-9a-f]{8}@example\.com$';
    IF bad > 0 THEN RAISE EXCEPTION 'orders.billing_email: % row(s) not masked', bad; END IF;

    -- name -> User <4 HEX>
    SELECT count(*) INTO bad FROM users WHERE full_name !~ '^User [0-9A-F]{4}$';
    IF bad > 0 THEN RAISE EXCEPTION 'users.full_name: % row(s) are not name-strategy output', bad; END IF;

    -- phone -> +1-555-<4 digits>
    SELECT count(*) INTO bad FROM users
     WHERE phone IS NOT NULL AND phone !~ '^\+1-555-\d{4}$';
    IF bad > 0 THEN RAISE EXCEPTION 'users.phone: % row(s) are not phone-strategy output', bad; END IF;

    -- redact -> the literal constant
    SELECT count(*) INTO bad FROM users WHERE ssn IS NOT NULL AND ssn <> '[REDACTED]';
    IF bad > 0 THEN RAISE EXCEPTION 'users.ssn: % row(s) not redacted', bad; END IF;

    -- hash -> 16 hex, one-way
    SELECT count(*) INTO bad FROM payments WHERE stripe_customer_id !~ '^[0-9a-f]{16}$';
    IF bad > 0 THEN RAISE EXCEPTION 'payments.stripe_customer_id: % row(s) are not hash output', bad; END IF;

    SELECT count(*) INTO bad FROM user_sessions
     WHERE ip_address IS NOT NULL AND ip_address !~ '^[0-9a-f]{16}$';
    IF bad > 0 THEN RAISE EXCEPTION 'user_sessions.ip_address: % row(s) are not hash output', bad; END IF;

    RAISE NOTICE '2. masked values have the shape each strategy promises';
END $$;

-- =============================================================================
-- 3. NULL stays NULL
--
-- Anonymizing a missing value into a present one invents data: staging would
-- show a phone number for a customer who never gave one, and any code path
-- branching on "has a phone" would be exercised wrongly.
-- =============================================================================

DO $$
DECLARE
    bad INTEGER;
BEGIN
    SELECT count(*) INTO bad FROM orders WHERE id = 2 AND customer_notes IS NOT NULL;
    IF bad > 0 THEN
        RAISE EXCEPTION 'orders.customer_notes: a NULL was masked into a value';
    END IF;
    RAISE NOTICE '3. NULL stayed NULL';
END $$;

-- =============================================================================
-- 4. Pseudonyms are stable, so the data is still joinable
--
-- The point of a keyed strategy over a random one. users.email and
-- orders.billing_email share a strategy and a seed, so one customer is one
-- pseudonym on both sides and "every order this customer placed" is still a
-- question staging can answer.
-- =============================================================================

DO $$
DECLARE
    mismatched INTEGER;
BEGIN
    SELECT count(*) INTO mismatched
      FROM orders o
      JOIN users u ON u.id = o.user_id
     WHERE o.billing_email IS NOT NULL
       AND o.billing_email <> u.email;
    IF mismatched > 0 THEN
        RAISE EXCEPTION
            'pseudonyms are not stable: % order(s) whose billing_email does not '
            'match the owning user''s masked email', mismatched;
    END IF;

    -- Same input, same output, within a table too: Alice placed orders 1 and 3.
    IF (SELECT count(DISTINCT billing_email) FROM orders WHERE user_id = 1) <> 1 THEN
        RAISE EXCEPTION 'one customer''s address masked to more than one pseudonym';
    END IF;

    RAISE NOTICE '4. pseudonyms are stable across tables';
END $$;

-- =============================================================================
-- 5. Different seeds give unrelated pseudonyms
--
-- employees uses seed 2 precisely so that a person who is both a customer and
-- an employee does not appear as the same pseudonym in both tables. Alice
-- (users.id 1, employees.id 2) is that person in the demo data.
-- =============================================================================

DO $$
DECLARE
    customer_pseudonym TEXT;
    staff_pseudonym    TEXT;
BEGIN
    SELECT email INTO customer_pseudonym FROM users     WHERE id = 1;
    SELECT email INTO staff_pseudonym    FROM employees WHERE id = 2;

    IF customer_pseudonym IS NULL OR staff_pseudonym IS NULL THEN
        RAISE EXCEPTION 'expected the demo rows for the customer-and-employee case';
    END IF;

    IF customer_pseudonym = staff_pseudonym THEN
        RAISE EXCEPTION
            'seed separation failed: the same address masked identically in '
            'users and employees (%), so the two roles can be correlated',
            customer_pseudonym;
    END IF;

    RAISE NOTICE '5. seeds separate staff pseudonyms from customer pseudonyms';
END $$;

-- =============================================================================
-- 6. Uniqueness survived where it has to
--
-- `hash` is used for stripe_customer_id rather than `redact` because
-- reconciliation code needs distinct customers to stay distinct. Two customers
-- collapsing to one value would pass check 1 and still break staging.
-- =============================================================================

DO $$
DECLARE
    distinct_sources INTEGER;
    distinct_masked  INTEGER;
BEGIN
    -- The demo has two distinct processor ids across three payments.
    SELECT count(DISTINCT stripe_customer_id) INTO distinct_masked FROM payments;
    distinct_sources := 2;
    IF distinct_masked <> distinct_sources THEN
        RAISE EXCEPTION
            'hash collapsed distinct values: % distinct processor ids became %',
            distinct_sources, distinct_masked;
    END IF;
    RAISE NOTICE '6. hash preserved uniqueness';
END $$;

-- =============================================================================
-- 7. Referential integrity survived
--
-- Masking touches columns, never keys — but a sync that copies tables in the
-- wrong order, or skips one, produces orphans. Cheap to check, and the failure
-- is confusing to debug from the application side.
-- =============================================================================

DO $$
DECLARE
    orphans INTEGER;
BEGIN
    SELECT count(*) INTO orphans FROM orders o LEFT JOIN users u ON u.id = o.user_id WHERE u.id IS NULL;
    IF orphans > 0 THEN RAISE EXCEPTION 'orders: % row(s) with no user', orphans; END IF;

    SELECT count(*) INTO orphans FROM payments p LEFT JOIN orders o ON o.id = p.order_id WHERE o.id IS NULL;
    IF orphans > 0 THEN RAISE EXCEPTION 'payments: % row(s) with no order', orphans; END IF;

    SELECT count(*) INTO orphans FROM order_items i LEFT JOIN orders o ON o.id = i.order_id WHERE o.id IS NULL;
    IF orphans > 0 THEN RAISE EXCEPTION 'order_items: % row(s) with no order', orphans; END IF;

    SELECT count(*) INTO orphans FROM support_tickets t LEFT JOIN users u ON u.id = t.user_id WHERE u.id IS NULL;
    IF orphans > 0 THEN RAISE EXCEPTION 'support_tickets: % row(s) with no user', orphans; END IF;

    RAISE NOTICE '7. referential integrity survived';
END $$;

-- =============================================================================
-- 8. The columns that were meant to survive, survived
--
-- Anonymization is opt-in per column: anything absent from
-- db/sync/anonymization.yaml is copied verbatim. That is easy to state and easy
-- to get wrong in the other direction — over-masking quietly destroys the
-- analytical value staging exists for.
-- =============================================================================

DO $$
DECLARE
    n INTEGER;
BEGIN
    SELECT count(*) INTO n FROM payments WHERE billing_zip IN ('02139', '02140');
    IF n <> 3 THEN RAISE EXCEPTION 'payments.billing_zip was masked; fraud rules need it (% of 3)', n; END IF;

    SELECT count(*) INTO n FROM user_sessions WHERE user_agent LIKE 'Mozilla/%';
    IF n <> 3 THEN RAISE EXCEPTION 'user_sessions.user_agent was masked; debugging needs it (% of 3)', n; END IF;

    SELECT count(*) INTO n FROM users WHERE country_code IN ('US', 'ES');
    IF n <> 3 THEN RAISE EXCEPTION 'users.country_code was masked (% of 3)', n; END IF;

    SELECT count(*) INTO n FROM orders WHERE total_cents > 0;
    IF n <> 3 THEN RAISE EXCEPTION 'orders.total_cents did not survive (% of 3)', n; END IF;

    RAISE NOTICE '8. non-PII columns survived intact';
END $$;

\echo '✅ verification passed: staging holds no source PII, and is still usable'
