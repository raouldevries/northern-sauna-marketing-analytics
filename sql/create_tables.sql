-- BigQuery DDL for Northern Sauna booking data
-- Canonical schema: source-system-agnostic booking records
--
-- Composite ID format:
--   Bookeo: {source_system}_{source_account}_{source_id} (3-part, prevents cross-account collisions)
--   Future systems with globally unique IDs: {source_system}_{source_id} (2-part)

CREATE TABLE IF NOT EXISTS `{project}.{dataset}.{table}` (
    -- Primary key
    id                  STRING NOT NULL,        -- Composite: {source_system}_{source_id}

    -- Source tracking
    source_system       STRING NOT NULL,        -- 'bookeo'
    source_account      STRING,                 -- Account identifier (e.g., 'stockholm', 'helsinki', 'oslo')
    source_id           STRING NOT NULL,        -- Original bookingNumber from Bookeo

    -- Customer information
    customer_email      STRING,
    customer_name       STRING,
    customer_phone      STRING,

    -- Booking details
    location            STRING,                 -- Normalized: 'Northern Sauna Stockholm', 'Northern Sauna Kamppi', etc.
    product_name        STRING,                 -- Raw productName from Bookeo
    booking_created_at  TIMESTAMP,
    visit_datetime      TIMESTAMP,
    status              STRING,                 -- 'confirmed', 'canceled', 'completed', 'no_show'
    participants        INT64,

    -- Financial
    currency            STRING DEFAULT 'EUR',
    gross_amount        NUMERIC,
    discount_amount     NUMERIC,
    net_amount          NUMERIC,
    paid_amount         NUMERIC,

    -- Metadata
    imported_at         TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP,
    raw_data            JSON
)
PARTITION BY DATE(visit_datetime)
CLUSTER BY location, source_system;
