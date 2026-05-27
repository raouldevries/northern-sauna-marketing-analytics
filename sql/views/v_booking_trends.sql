-- Daily booking aggregations by location and status.
--
-- Usage:
--   SELECT * FROM `demo-project.demo_data.v_booking_trends`
--     WHERE date >= '2025-01-01' AND location = 'Northern Sauna Stockholm'
--   SELECT * FROM `demo-project.demo_data.v_booking_trends`
--     WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

-- Bookings semantics: prefer `bookings_excl_canceled` (canonical default,
-- matches dashboards) or `bookings_total` (all statuses). The bare
-- `bookings` column is preserved as a legacy alias of `bookings_total`
-- for backwards compat with any ad-hoc consumers outside this repo.
CREATE OR REPLACE VIEW `demo-project.demo_data.v_booking_trends` AS
SELECT
  DATE(visit_datetime) AS date,
  location,
  COUNT(*) AS bookings,
  COUNT(*) AS bookings_total,
  COUNTIF(status != 'canceled') AS bookings_excl_canceled,
  SUM(participants) AS participants,
  SUM(net_amount) AS revenue,
  COUNTIF(status = 'canceled') AS cancellations,
  COUNTIF(status = 'no_show') AS no_shows,
  COUNTIF(status = 'completed') AS completed,
  COUNTIF(status = 'confirmed') AS confirmed
FROM `demo-project.demo_data.bookings`
WHERE visit_datetime IS NOT NULL
GROUP BY date, location
