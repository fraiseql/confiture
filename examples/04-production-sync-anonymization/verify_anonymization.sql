-- Confiture Anonymization Verification SQL
-- Production Data Sync - Example 04
--
-- This SQL script verifies that PII has been properly anonymized after
-- syncing production data to staging/local environments.
--
-- Usage:
--   psql postgresql://staging-host/staging_db < verify_anonymization.sql
--
-- Expected Result: All checks should return 0 violations

\set ON_ERROR_STOP on
\timing on
\pset border 2

\echo ''
\echo '============================================================================'
\echo '  Confiture Anonymization Verification Report'
\echo '============================================================================'
\echo ''
\echo 'Database: ' :DBNAME
\echo 'Host: ' :HOST
\echo 'Date: ' `date`
\echo ''

-- ============================================================================
-- Test 1: Email Anonymization Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 1: Email Anonymization Check'
\echo '--------------------------------------------------------------------'
\echo 'Verifying all emails are anonymized to @anon.local domain'
\echo ''

WITH email_check AS (
    SELECT
        'users.email' AS column_name,
        COUNT(*) AS total_emails,
        COUNT(*) FILTER (WHERE email LIKE '%@anon.local') AS anonymized,
        COUNT(*) FILTER (WHERE email NOT LIKE '%@anon.local') AS violations
    FROM users
    WHERE email IS NOT NULL

    UNION ALL

    SELECT
        'users.backup_email' AS column_name,
        COUNT(*) AS total_emails,
        COUNT(*) FILTER (WHERE backup_email LIKE '%@anon.local') AS anonymized,
        COUNT(*) FILTER (WHERE backup_email NOT LIKE '%@anon.local') AS violations
    FROM users
    WHERE backup_email IS NOT NULL

    UNION ALL

    SELECT
        'orders.billing_email' AS column_name,
        COUNT(*) AS total_emails,
        COUNT(*) FILTER (WHERE billing_email LIKE '%@anon.local') AS anonymized,
        COUNT(*) FILTER (WHERE billing_email NOT LIKE '%@anon.local') AS violations
    FROM orders
    WHERE billing_email IS NOT NULL

    UNION ALL

    SELECT
        'marketing_subscriptions.email' AS column_name,
        COUNT(*) AS total_emails,
        COUNT(*) FILTER (WHERE email LIKE '%@anon.local') AS anonymized,
        COUNT(*) FILTER (WHERE email NOT LIKE '%@anon.local') AS violations
    FROM marketing_subscriptions
    WHERE email IS NOT NULL
)
SELECT
    column_name,
    total_emails,
    anonymized,
    violations,
    CASE
        WHEN violations = 0 THEN '✓ PASS'
        ELSE '✗ FAIL'
    END AS status
FROM email_check
ORDER BY column_name;

-- Overall email check
SELECT
    'Email Anonymization' AS test_name,
    SUM(violations) AS total_violations,
    CASE
        WHEN SUM(violations) = 0 THEN '✓ PASS'
        ELSE '✗ FAIL - LEAKED EMAILS DETECTED'
    END AS overall_status
FROM (
    SELECT COUNT(*) FILTER (WHERE email NOT LIKE '%@anon.local') AS violations
    FROM users WHERE email IS NOT NULL
    UNION ALL
    SELECT COUNT(*) FILTER (WHERE backup_email NOT LIKE '%@anon.local')
    FROM users WHERE backup_email IS NOT NULL
    UNION ALL
    SELECT COUNT(*) FILTER (WHERE billing_email NOT LIKE '%@anon.local')
    FROM orders WHERE billing_email IS NOT NULL
    UNION ALL
    SELECT COUNT(*) FILTER (WHERE email NOT LIKE '%@anon.local')
    FROM marketing_subscriptions WHERE email IS NOT NULL
) AS all_violations;

-- ============================================================================
-- Test 2: Phone Number Anonymization Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 2: Phone Number Anonymization Check'
\echo '--------------------------------------------------------------------'
\echo 'Verifying phone numbers are anonymized (should use 555 area code)'
\echo ''

WITH phone_check AS (
    SELECT
        'users.phone' AS column_name,
        COUNT(*) AS total_phones,
        COUNT(*) FILTER (WHERE phone LIKE '%555-%') AS anonymized,
        COUNT(*) FILTER (WHERE phone !~ '^.*555-.*$') AS violations
    FROM users
    WHERE phone IS NOT NULL

    UNION ALL

    SELECT
        'users.mobile_phone' AS column_name,
        COUNT(*) AS total_phones,
        COUNT(*) FILTER (WHERE mobile_phone LIKE '%555-%') AS anonymized,
        COUNT(*) FILTER (WHERE mobile_phone !~ '^.*555-.*$') AS violations
    FROM users
    WHERE mobile_phone IS NOT NULL

    UNION ALL

    SELECT
        'employees.phone' AS column_name,
        COUNT(*) AS total_phones,
        COUNT(*) FILTER (WHERE phone LIKE '%555-%') AS anonymized,
        COUNT(*) FILTER (WHERE phone !~ '^.*555-.*$') AS violations
    FROM employees
    WHERE phone IS NOT NULL
)
SELECT
    column_name,
    total_phones,
    anonymized,
    violations,
    CASE
        WHEN violations = 0 THEN '✓ PASS'
        ELSE '✗ FAIL'
    END AS status
FROM phone_check
ORDER BY column_name;

-- Check for real area codes (should not exist)
SELECT
    'Real Area Codes' AS test_name,
    COUNT(*) AS violations,
    CASE
        WHEN COUNT(*) = 0 THEN '✓ PASS'
        ELSE '✗ FAIL - REAL PHONE NUMBERS DETECTED'
    END AS status
FROM users
WHERE phone ~ '^[0-9]{3}-[0-9]{3}-[0-9]{4}$'
  AND phone NOT LIKE '555-%'
  AND phone IS NOT NULL;

-- ============================================================================
-- Test 3: SSN Redaction Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 3: SSN Redaction Check'
\echo '--------------------------------------------------------------------'
\echo 'Verifying SSNs are fully redacted (***-**-****)'
\echo ''

WITH ssn_check AS (
    SELECT
        'users.ssn' AS column_name,
        COUNT(*) AS total_ssns,
        COUNT(*) FILTER (WHERE ssn = '***-**-****') AS redacted,
        COUNT(*) FILTER (WHERE ssn ~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$') AS violations
    FROM users
    WHERE ssn IS NOT NULL

    UNION ALL

    SELECT
        'employees.ssn' AS column_name,
        COUNT(*) AS total_ssns,
        COUNT(*) FILTER (WHERE ssn = '***-**-****') AS redacted,
        COUNT(*) FILTER (WHERE ssn ~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$') AS violations
    FROM employees
    WHERE ssn IS NOT NULL
)
SELECT
    column_name,
    total_ssns,
    redacted,
    violations,
    CASE
        WHEN violations = 0 THEN '✓ PASS'
        ELSE '✗ FAIL'
    END AS status
FROM ssn_check
ORDER BY column_name;

-- Overall SSN check
SELECT
    'SSN Redaction' AS test_name,
    SUM(violations) AS total_violations,
    CASE
        WHEN SUM(violations) = 0 THEN '✓ PASS'
        ELSE '✗ FAIL - UNREDACTED SSNs DETECTED'
    END AS overall_status
FROM (
    SELECT COUNT(*) FILTER (WHERE ssn ~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$') AS violations
    FROM users WHERE ssn IS NOT NULL
    UNION ALL
    SELECT COUNT(*) FILTER (WHERE ssn ~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$')
    FROM employees WHERE ssn IS NOT NULL
) AS all_violations;

-- ============================================================================
-- Test 4: Address Anonymization Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 4: Address Anonymization Check'
\echo '--------------------------------------------------------------------'
\echo 'Verifying addresses are redacted (street removed, geo data preserved)'
\echo ''

WITH address_check AS (
    SELECT
        'orders.billing_address' AS column_name,
        COUNT(*) AS total_addresses,
        COUNT(*) FILTER (WHERE billing_address LIKE '[REDACTED]%') AS anonymized,
        COUNT(*) FILTER (WHERE billing_address NOT LIKE '[REDACTED]%') AS violations
    FROM orders
    WHERE billing_address IS NOT NULL

    UNION ALL

    SELECT
        'orders.shipping_address' AS column_name,
        COUNT(*) AS total_addresses,
        COUNT(*) FILTER (WHERE shipping_address LIKE '[REDACTED]%') AS anonymized,
        COUNT(*) FILTER (WHERE shipping_address NOT LIKE '[REDACTED]%') AS violations
    FROM orders
    WHERE shipping_address IS NOT NULL

    UNION ALL

    SELECT
        'employees.home_address' AS column_name,
        COUNT(*) AS total_addresses,
        COUNT(*) FILTER (WHERE home_address LIKE '[REDACTED]%' OR home_address = '[REDACTED ADDRESS]') AS anonymized,
        COUNT(*) FILTER (WHERE home_address NOT LIKE '[REDACTED]%' AND home_address != '[REDACTED ADDRESS]') AS violations
    FROM employees
    WHERE home_address IS NOT NULL
)
SELECT
    column_name,
    total_addresses,
    anonymized,
    violations,
    CASE
        WHEN violations = 0 THEN '✓ PASS'
        ELSE '✗ FAIL'
    END AS status
FROM address_check
ORDER BY column_name;

-- ============================================================================
-- Test 5: Name Anonymization Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 5: Name Anonymization Check'
\echo '--------------------------------------------------------------------'
\echo 'Verifying names are anonymized (should start with User- or similar)'
\echo ''

WITH name_check AS (
    SELECT
        'users.first_name' AS column_name,
        COUNT(*) AS total_names,
        COUNT(*) FILTER (WHERE first_name LIKE 'User-%') AS anonymized,
        COUNT(*) FILTER (WHERE first_name NOT LIKE 'User-%') AS violations
    FROM users
    WHERE first_name IS NOT NULL

    UNION ALL

    SELECT
        'users.last_name' AS column_name,
        COUNT(*) AS total_names,
        COUNT(*) FILTER (WHERE last_name LIKE 'User-%') AS anonymized,
        COUNT(*) FILTER (WHERE last_name NOT LIKE 'User-%') AS violations
    FROM users
    WHERE last_name IS NOT NULL
)
SELECT
    column_name,
    total_names,
    anonymized,
    violations,
    CASE
        WHEN violations = 0 THEN '✓ PASS'
        WHEN violations < total_names * 0.05 THEN '⚠ WARNING'
        ELSE '✗ FAIL'
    END AS status
FROM name_check
ORDER BY column_name;

-- ============================================================================
-- Test 6: Payment Data Redaction Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 6: Payment Data Redaction Check'
\echo '--------------------------------------------------------------------'
\echo 'Verifying credit card and payment data is redacted'
\echo ''

SELECT
    'payments.card_last4' AS column_name,
    COUNT(*) AS total_cards,
    COUNT(*) FILTER (WHERE card_last4 = '****') AS redacted,
    COUNT(*) FILTER (WHERE card_last4 ~ '^[0-9]{4}$') AS violations,
    CASE
        WHEN COUNT(*) FILTER (WHERE card_last4 ~ '^[0-9]{4}$') = 0 THEN '✓ PASS'
        ELSE '✗ FAIL'
    END AS status
FROM payments
WHERE card_last4 IS NOT NULL;

-- Check Stripe customer IDs are anonymized
SELECT
    'payments.stripe_customer_id' AS column_name,
    COUNT(*) AS total_ids,
    COUNT(*) FILTER (WHERE stripe_customer_id LIKE 'cus_%') AS anonymized,
    CASE
        WHEN COUNT(*) = COUNT(*) FILTER (WHERE stripe_customer_id LIKE 'cus_%') THEN '✓ PASS'
        ELSE '✗ FAIL'
    END AS status
FROM payments
WHERE stripe_customer_id IS NOT NULL;

-- ============================================================================
-- Test 7: IP Address Anonymization Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 7: IP Address Anonymization Check'
\echo '--------------------------------------------------------------------'
\echo 'Verifying IP addresses are anonymized (last 2 octets should be masked)'
\echo ''

SELECT
    'user_sessions.ip_address' AS column_name,
    COUNT(*) AS total_ips,
    COUNT(*) FILTER (WHERE ip_address ~ '\d+\.\d+\.0\.0$') AS anonymized,
    COUNT(*) FILTER (WHERE ip_address !~ '\d+\.\d+\.0\.0$') AS violations,
    CASE
        WHEN COUNT(*) FILTER (WHERE ip_address !~ '\d+\.\d+\.0\.0$') = 0 THEN '✓ PASS'
        ELSE '✗ FAIL'
    END AS status
FROM user_sessions
WHERE ip_address IS NOT NULL;

-- ============================================================================
-- Test 8: Referential Integrity Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 8: Referential Integrity Check'
\echo '--------------------------------------------------------------------'
\echo 'Verifying foreign key relationships remain valid after anonymization'
\echo ''

-- Orders → Users
SELECT
    'orders.user_id → users.id' AS foreign_key,
    COUNT(*) AS total_orders,
    COUNT(u.id) AS valid_references,
    COUNT(*) - COUNT(u.id) AS violations,
    CASE
        WHEN COUNT(*) = COUNT(u.id) THEN '✓ PASS'
        ELSE '✗ FAIL - ORPHANED ORDERS'
    END AS status
FROM orders o
LEFT JOIN users u ON o.user_id = u.id;

-- Order items → Orders
SELECT
    'order_items.order_id → orders.id' AS foreign_key,
    COUNT(*) AS total_items,
    COUNT(ord.id) AS valid_references,
    COUNT(*) - COUNT(ord.id) AS violations,
    CASE
        WHEN COUNT(*) = COUNT(ord.id) THEN '✓ PASS'
        ELSE '✗ FAIL - ORPHANED ORDER ITEMS'
    END AS status
FROM order_items oi
LEFT JOIN orders ord ON oi.order_id = ord.id;

-- Order items → Products
SELECT
    'order_items.product_id → products.id' AS foreign_key,
    COUNT(*) AS total_items,
    COUNT(p.id) AS valid_references,
    COUNT(*) - COUNT(p.id) AS violations,
    CASE
        WHEN COUNT(*) = COUNT(p.id) THEN '✓ PASS'
        ELSE '✗ FAIL - ORPHANED PRODUCT REFERENCES'
    END AS status
FROM order_items oi
LEFT JOIN products p ON oi.product_id = p.id;

-- Payments → Orders
SELECT
    'payments.order_id → orders.id' AS foreign_key,
    COUNT(*) AS total_payments,
    COUNT(ord.id) AS valid_references,
    COUNT(*) - COUNT(ord.id) AS violations,
    CASE
        WHEN COUNT(*) = COUNT(ord.id) THEN '✓ PASS'
        ELSE '✗ FAIL - ORPHANED PAYMENTS'
    END AS status
FROM payments p
LEFT JOIN orders ord ON p.order_id = ord.id;

-- ============================================================================
-- Test 9: Text Field PII Pattern Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 9: Text Field PII Pattern Check'
\echo '--------------------------------------------------------------------'
\echo 'Searching for PII patterns in text fields (notes, comments, reviews)'
\echo ''

-- Check for email patterns in order notes
SELECT
    'orders.customer_notes (email pattern)' AS field,
    COUNT(*) AS violations,
    CASE
        WHEN COUNT(*) = 0 THEN '✓ PASS'
        ELSE '✗ FAIL - EMAILS IN TEXT FIELDS'
    END AS status
FROM orders
WHERE customer_notes ~ '\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b';

-- Check for phone patterns in order notes
SELECT
    'orders.customer_notes (phone pattern)' AS field,
    COUNT(*) AS violations,
    CASE
        WHEN COUNT(*) = 0 THEN '✓ PASS'
        ELSE '✗ FAIL - PHONE NUMBERS IN TEXT FIELDS'
    END AS status
FROM orders
WHERE customer_notes ~ '\b\d{3}[-.]?\d{3}[-.]?\d{4}\b';

-- Check for SSN patterns in order notes
SELECT
    'orders.customer_notes (SSN pattern)' AS field,
    COUNT(*) AS violations,
    CASE
        WHEN COUNT(*) = 0 THEN '✓ PASS'
        ELSE '✗ FAIL - SSNs IN TEXT FIELDS'
    END AS status
FROM orders
WHERE customer_notes ~ '\b\d{3}-\d{2}-\d{4}\b';

-- Check for email patterns in support tickets
SELECT
    'support_tickets.body (email pattern)' AS field,
    COUNT(*) AS violations,
    CASE
        WHEN COUNT(*) = 0 THEN '✓ PASS'
        ELSE '✗ FAIL - EMAILS IN SUPPORT TICKETS'
    END AS status
FROM support_tickets
WHERE body ~ '\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b';

-- Check for email patterns in product reviews
SELECT
    'product_reviews.review_text (email pattern)' AS field,
    COUNT(*) AS violations,
    CASE
        WHEN COUNT(*) = 0 THEN '✓ PASS'
        ELSE '✗ FAIL - EMAILS IN REVIEWS'
    END AS status
FROM product_reviews
WHERE review_text ~ '\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b';

-- ============================================================================
-- Test 10: Data Completeness Check
-- ============================================================================

\echo ''
\echo '--------------------------------------------------------------------'
\echo 'Test 10: Data Completeness Check'
\echo '--------------------------------------------------------------------'
\echo 'Verifying data was copied completely (no missing rows)'
\echo ''

-- Count rows per table
SELECT
    'users' AS table_name,
    COUNT(*) AS row_count,
    CASE
        WHEN COUNT(*) > 0 THEN '✓ HAS DATA'
        ELSE '⚠ EMPTY TABLE'
    END AS status
FROM users

UNION ALL

SELECT
    'orders' AS table_name,
    COUNT(*) AS row_count,
    CASE
        WHEN COUNT(*) > 0 THEN '✓ HAS DATA'
        ELSE '⚠ EMPTY TABLE'
    END AS status
FROM orders

UNION ALL

SELECT
    'order_items' AS table_name,
    COUNT(*) AS row_count,
    CASE
        WHEN COUNT(*) > 0 THEN '✓ HAS DATA'
        ELSE '⚠ EMPTY TABLE'
    END AS status
FROM order_items

UNION ALL

SELECT
    'products' AS table_name,
    COUNT(*) AS row_count,
    CASE
        WHEN COUNT(*) > 0 THEN '✓ HAS DATA'
        ELSE '⚠ EMPTY TABLE'
    END AS status
FROM products

ORDER BY table_name;

-- ============================================================================
-- Final Summary
-- ============================================================================

\echo ''
\echo '============================================================================'
\echo '  Verification Summary'
\echo '============================================================================'
\echo ''

-- Overall summary query
WITH all_checks AS (
    SELECT 'Email Anonymization' AS check_name,
           CASE WHEN (SELECT COUNT(*) FROM users WHERE email NOT LIKE '%@anon.local' AND email IS NOT NULL) = 0
                THEN 'PASS' ELSE 'FAIL' END AS result
    UNION ALL
    SELECT 'Phone Anonymization',
           CASE WHEN (SELECT COUNT(*) FROM users WHERE phone !~ '^.*555-.*$' AND phone IS NOT NULL) = 0
                THEN 'PASS' ELSE 'FAIL' END
    UNION ALL
    SELECT 'SSN Redaction',
           CASE WHEN (SELECT COUNT(*) FROM users WHERE ssn ~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$' AND ssn IS NOT NULL) = 0
                THEN 'PASS' ELSE 'FAIL' END
    UNION ALL
    SELECT 'Address Anonymization',
           CASE WHEN (SELECT COUNT(*) FROM orders WHERE billing_address NOT LIKE '[REDACTED]%' AND billing_address IS NOT NULL) = 0
                THEN 'PASS' ELSE 'FAIL' END
    UNION ALL
    SELECT 'Payment Data Redaction',
           CASE WHEN (SELECT COUNT(*) FROM payments WHERE card_last4 ~ '^[0-9]{4}$' AND card_last4 IS NOT NULL) = 0
                THEN 'PASS' ELSE 'FAIL' END
    UNION ALL
    SELECT 'Referential Integrity',
           CASE WHEN (SELECT COUNT(*) FROM orders o LEFT JOIN users u ON o.user_id = u.id WHERE u.id IS NULL) = 0
                THEN 'PASS' ELSE 'FAIL' END
)
SELECT
    check_name,
    result,
    CASE
        WHEN result = 'PASS' THEN '✓'
        ELSE '✗'
    END AS icon
FROM all_checks
ORDER BY check_name;

-- Final verdict
\echo ''
SELECT
    CASE
        WHEN COUNT(*) FILTER (WHERE result = 'FAIL') = 0
        THEN '✓✓✓ ALL CHECKS PASSED - DATABASE IS SAFE TO USE ✓✓✓'
        ELSE '✗✗✗ SOME CHECKS FAILED - DO NOT USE THIS DATABASE ✗✗✗'
    END AS final_verdict
FROM (
    SELECT CASE WHEN (SELECT COUNT(*) FROM users WHERE email NOT LIKE '%@anon.local' AND email IS NOT NULL) = 0
                THEN 'PASS' ELSE 'FAIL' END AS result
    UNION ALL
    SELECT CASE WHEN (SELECT COUNT(*) FROM users WHERE phone !~ '^.*555-.*$' AND phone IS NOT NULL) = 0
                THEN 'PASS' ELSE 'FAIL' END
    UNION ALL
    SELECT CASE WHEN (SELECT COUNT(*) FROM users WHERE ssn ~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$' AND ssn IS NOT NULL) = 0
                THEN 'PASS' ELSE 'FAIL' END
) AS all_results;

\echo ''
\echo '============================================================================'
\echo '  End of Verification Report'
\echo '============================================================================'
\echo ''
