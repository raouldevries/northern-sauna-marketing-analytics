-- View for easy querying of the latest freshness check results.
-- Run create_monitoring_dataset.sh first to create the dataset.
--
-- Usage:
--   SELECT * FROM `demo-project.demo_monitoring.v_data_freshness`
--   SELECT * FROM `demo-project.demo_monitoring.v_data_freshness` WHERE status = 'STALE'

CREATE OR REPLACE VIEW `demo-project.demo_monitoring.v_data_freshness` AS
SELECT
  source,
  dataset,
  latest_data_date,
  total_rows,
  days_since_latest,
  staleness_threshold_days,
  status,
  checked_at
FROM `demo-project.demo_monitoring.data_freshness_log`
