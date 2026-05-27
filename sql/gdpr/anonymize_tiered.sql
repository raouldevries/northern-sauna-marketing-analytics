-- GDPR Tiered Anonymization for Bookings
-- Idempotent: running multiple times produces the same result.
--
-- Tier 1 (2-5 years old): NULL PII columns + raw_data
-- Tier 2 (5+ years old): NULL PII + set customer_name to 'ANONYMIZED'
--
-- Uses {project}, {dataset}, {table} placeholders (resolved at runtime).

-- Tier 2 first (5+ years) — more restrictive, prevents Tier 1 from overwriting
UPDATE `{project}.{dataset}.{table}`
SET
    customer_email = NULL,
    customer_name = 'ANONYMIZED',
    customer_phone = NULL,
    raw_data = NULL,
    updated_at = CURRENT_TIMESTAMP()
WHERE visit_datetime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1825 DAY)
  AND (customer_email IS NOT NULL
       OR customer_name != 'ANONYMIZED'
       OR customer_phone IS NOT NULL
       OR raw_data IS NOT NULL);

-- Tier 1 (2-5 years) — NULL PII but keep customer_name as-is (not 'ANONYMIZED')
UPDATE `{project}.{dataset}.{table}`
SET
    customer_email = NULL,
    customer_name = NULL,
    customer_phone = NULL,
    raw_data = NULL,
    updated_at = CURRENT_TIMESTAMP()
WHERE visit_datetime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
  AND visit_datetime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1825 DAY)
  AND (customer_name IS NULL OR customer_name != 'ANONYMIZED')
  AND (customer_email IS NOT NULL
       OR customer_name IS NOT NULL
       OR customer_phone IS NOT NULL
       OR raw_data IS NOT NULL);
