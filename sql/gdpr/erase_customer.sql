-- GDPR Art. 17 Right to Erasure
-- Erases all PII for a given customer email.
-- Idempotent: running twice produces the same result.
--
-- Uses @customer_email query parameter and {project}, {dataset}, {table} placeholders.

UPDATE `{project}.{dataset}.{table}`
SET
    customer_email = NULL,
    customer_name = 'ERASED',
    customer_phone = NULL,
    raw_data = NULL,
    updated_at = CURRENT_TIMESTAMP()
WHERE customer_email = @customer_email
  AND (customer_name IS NULL OR customer_name != 'ERASED');
