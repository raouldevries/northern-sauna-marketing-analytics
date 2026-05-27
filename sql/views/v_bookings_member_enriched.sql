-- Row-level enrichment of `bookings` with denormalized membership fields.
-- One row per booking (no aggregation). Pass-through view so partition pruning
-- on `visit_datetime` from callers flows through to the underlying table.
--
-- Deploy:
--   bq query --use_legacy_sql=false --project_id=demo-project \
--            --location=europe-west4 < sql/views/v_bookings_member_enriched.sql
--
-- Usage (canonical — matches Members page semantics):
--   SELECT COUNT(*) FROM `demo-project.demo_data.v_bookings_member_enriched`
--     WHERE DATE(visit_datetime) BETWEEN '2026-04-01' AND '2026-04-30'
--       AND status != 'canceled'   -- Members page operates on df2 (non-canceled)
--       AND is_member;
--
-- Default semantics — IMPORTANT:
--   "Member bookings" in business reporting means NON-CANCELED member bookings.
--   The Members page (`streamlit/pages/4_members.py`) reads `df2`, which is
--   filtered to `status != 'canceled'` upstream (`streamlit/data/queries.py:207`).
--   Any chatbot query, parity check, or KPI that omits `status != 'canceled'`
--   will overcount relative to the page.
--
-- Last-synced semantics — IMPORTANT:
--   `is_member` reflects the LAST-SYNCED value of customer.member on the booking
--   row. The Bookeo sync (scripts/daily_sync.py) re-fetches recent bookings on a
--   rolling window and MERGE-overwrites raw_data (src/utils/bigquery.py:75), so
--   the field is "what Bookeo reported about this customer the last time we
--   synced this row" — NOT a guaranteed snapshot of membership at booking time,
--   and NOT a guaranteed reflection of current customer status.
--
--   This view is the operational source of truth for the Members page and the
--   Ask-the-Data chatbot. It is NOT a basis for historical-truth claims about
--   membership lifecycle. See plans/member-metric-parity-plan.md (Future Work)
--   for the longer-term temporal-membership backlog.
--
-- NULL handling:
--   `is_member` is wrapped in COALESCE(..., FALSE) so it is never NULL — this
--   matches `streamlit/data/queries.py:194` which coerces missing flags to
--   non-member. NULL is_member would otherwise leak into BigQuery as a third
--   bucket and silently drop rows from `WHERE NOT is_member` and `GROUP BY
--   is_member` paths. Sources of NULL raw_data:
--     - bookings ingested with customer=null (src/bookeo/transform.py)
--     - GDPR-anonymized rows after 730 days (sql/gdpr/anonymize_tiered.sql)
--
-- PII:
--   `raw_data` is passed through unchanged. The catalog entry for this view
--   MUST tag `raw_data` (and the email/name/phone columns) as `pii: true` so
--   sql_safety.py blocks chatbot SELECTs. `customer_email_hash` is a
--   pseudonymous internal identifier — not safe for external publication.

CREATE OR REPLACE VIEW `demo-project.demo_data.v_bookings_member_enriched` AS
SELECT
  -- Identity
  id,
  source_system,
  source_account,
  source_id,

  -- Customer (PII — block in catalog)
  customer_email,
  customer_name,
  customer_phone,
  -- Pseudonymous identifier matching `streamlit/data/queries.py:149`
  -- normalization (LOWER/TRIM/COALESCE) so chatbot COUNT(DISTINCT ...) equals
  -- page-side nunique() exactly.
  TO_HEX(SHA256(LOWER(TRIM(COALESCE(customer_email, ''))))) AS customer_email_hash,

  -- Booking details
  location,
  product_name,
  booking_created_at,
  visit_datetime,
  status,
  participants,

  -- Financial
  currency,
  gross_amount,
  discount_amount,
  net_amount,
  paid_amount,

  -- Metadata
  imported_at,
  updated_at,

  -- Pass-through JSON (PII — block in catalog). Page still extracts
  -- promotion/source/cancelation/etc. from this column; see queries.py:69-81.
  raw_data,

  -- Membership (denormalized from raw_data.customer.*).
  -- COALESCE on is_member so NULL raw_data / NULL customer never produces
  -- NULL is_member — matches page-side fillna("false") behavior.
  COALESCE(LOWER(JSON_VALUE(raw_data, '$.customer.member')) = 'true', FALSE) AS is_member,
  SAFE.PARSE_DATE('%Y-%m-%d', JSON_VALUE(raw_data, '$.customer.membershipEnd')) AS membership_end
FROM `demo-project.demo_data.bookings`
