-- GDPR-compliant analytics view
-- Excludes PII columns (customer_email, customer_name, customer_phone, raw_data)
-- for data-minimized access by analytics users.
--
-- Uses {project}, {dataset}, {table} placeholders.

CREATE OR REPLACE VIEW `{project}.{dataset}.bookings_anonymized` AS
SELECT
    id,
    source_system,
    source_account,
    source_id,
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
FROM `{project}.{dataset}.{table}`;
