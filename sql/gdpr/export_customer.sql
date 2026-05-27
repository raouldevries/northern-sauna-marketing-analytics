-- GDPR Art. 15 Right of Access (Data Export)
-- Returns all records for a given customer email.
--
-- Uses @customer_email query parameter and {project}, {dataset}, {table} placeholders.

SELECT
    id,
    source_system,
    source_account,
    source_id,
    customer_email,
    customer_name,
    customer_phone,
    location,
    product_name,
    booking_created_at,
    visit_datetime,
    status,
    participants,
    currency,
    gross_amount,
    discount_amount,
    net_amount,
    paid_amount,
    imported_at,
    updated_at
FROM `{project}.{dataset}.{table}`
WHERE customer_email = @customer_email
ORDER BY visit_datetime DESC;
