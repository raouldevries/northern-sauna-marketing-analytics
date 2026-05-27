-- Data freshness check for all marketing data sources.
-- Designed to run as a BigQuery scheduled query (daily, 09:00 UTC).
-- Destination: demo_monitoring.data_freshness_log (WRITE_TRUNCATE).
--
-- Staleness thresholds:
--   GA4 native export: 3 days
--   Google Ads:        3 days
--   Search Console:    5 days (2-3 day natural lag)
--   Meta Ads:          3 days
--   GMB Reviews:       8 days

WITH sources AS (
  -- GA4 native export: latest events_YYYYMMDD table
  SELECT
    'ga4_native_export' AS source,
    'analytics_000000000' AS dataset,
    MAX(PARSE_DATE('%Y%m%d', REGEXP_EXTRACT(table_id, r'events_(\d{8})'))) AS latest_data_date,
    SUM(row_count) AS total_rows,
    3 AS staleness_threshold_days
  FROM `demo-project.analytics_000000000.__TABLES__`
  WHERE table_id LIKE 'events_%'

  UNION ALL

  -- Google Ads (main transfer): latest segments_date across campaign stats
  SELECT
    'google_ads' AS source,
    'google_ads' AS dataset,
    MAX(segments_date) AS latest_data_date,
    NULL AS total_rows,
    3 AS staleness_threshold_days
  FROM `demo-project.google_ads.ads_CampaignBasicStats_2079223948`

  UNION ALL

  -- Google Ads PMax/RSA asset transfer (separate custom transfer —
  -- northern_sauna-google-ads-pmax-creative — writes to a different dataset).
  -- Without this row, a silent failure in the custom transfer goes
  -- unnoticed while the main transfer looks healthy. (Happened 2026-04-01
  -- through 2026-04-17.)
  SELECT
    'google_ads_pmax' AS source,
    'google_ads_pmax' AS dataset,
    MAX(segments_date) AS latest_data_date,
    NULL AS total_rows,
    3 AS staleness_threshold_days
  FROM `demo-project.google_ads_pmax.p_ads_AssetGroupAssetMetrics_2079223948`

  UNION ALL

  -- Search Console: latest data_date
  SELECT
    'search_console' AS source,
    'searchconsole' AS dataset,
    MAX(data_date) AS latest_data_date,
    COUNT(*) AS total_rows,
    5 AS staleness_threshold_days
  FROM `demo-project.searchconsole.searchdata_site_impression`

  UNION ALL

  -- Meta Ads: latest date_start from ads_insights
  SELECT
    'meta_ads' AS source,
    'meta_ads' AS dataset,
    MAX(date_start) AS latest_data_date,
    COUNT(*) AS total_rows,
    3 AS staleness_threshold_days
  FROM `demo-project.meta_ads.ads_insights`
)

SELECT
  source,
  dataset,
  latest_data_date,
  total_rows,
  DATE_DIFF(CURRENT_DATE(), latest_data_date, DAY) AS days_since_latest,
  staleness_threshold_days,
  CASE
    WHEN DATE_DIFF(CURRENT_DATE(), latest_data_date, DAY) <= staleness_threshold_days THEN 'OK'
    ELSE 'STALE'
  END AS status,
  CURRENT_TIMESTAMP() AS checked_at
FROM sources
ORDER BY source
