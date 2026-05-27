-- Cross-channel daily marketing summary.
-- Aggregates daily metrics from Google Ads, Meta Ads, GA4, and Search Console.
--
-- Usage:
--   SELECT * FROM `demo-project.demo_data.v_daily_marketing_summary`
--     WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
--   SELECT * FROM `demo-project.demo_data.v_daily_marketing_summary`
--     WHERE source = 'google_ads' ORDER BY date DESC

CREATE OR REPLACE VIEW `demo-project.demo_data.v_daily_marketing_summary` AS

-- Google Ads: daily campaign stats aggregated
SELECT
  s.segments_date AS date,
  'google_ads' AS source,
  SUM(s.metrics_impressions) AS impressions,
  SUM(s.metrics_clicks) AS clicks,
  SUM(s.metrics_cost_micros) / 1e6 AS spend,
  NULL AS sessions,
  NULL AS conversions
FROM `demo-project.google_ads.ads_CampaignBasicStats_2079223948` s
GROUP BY s.segments_date

UNION ALL

-- Meta Ads: daily insights aggregated
SELECT
  date_start AS date,
  'meta_ads' AS source,
  SUM(impressions) AS impressions,
  SUM(clicks) AS clicks,
  SUM(CAST(spend AS FLOAT64)) AS spend,
  NULL AS sessions,
  NULL AS conversions
FROM `demo-project.meta_ads.ads_insights`
GROUP BY date_start

UNION ALL

-- GA4: sessions and conversions from native export (Feb 24, 2026 onward)
SELECT
  PARSE_DATE('%Y%m%d', event_date) AS date,
  'ga4' AS source,
  NULL AS impressions,
  NULL AS clicks,
  NULL AS spend,
  COUNTIF(event_name = 'session_start') AS sessions,
  COUNTIF(event_name = 'purchase') AS conversions
FROM `demo-project.analytics_000000000.events_*`
WHERE event_name IN ('session_start', 'purchase')
  AND _TABLE_SUFFIX >= '20260224'
  AND _TABLE_SUFFIX NOT LIKE 'intraday%'
GROUP BY event_date

UNION ALL

-- GA4: sessions and conversions from historical backfill (before native export)
SELECT
  date,
  'ga4' AS source,
  NULL AS impressions,
  NULL AS clicks,
  NULL AS spend,
  SUM(sessions) AS sessions,
  SUM(key_events) AS conversions
FROM `demo-project.analytics_000000000_historical.daily_traffic`
WHERE date < DATE '2026-02-24'
GROUP BY date

UNION ALL

-- Search Console: organic search impressions and clicks (historical backfill)
SELECT
  data_date AS date,
  'search_console' AS source,
  SUM(impressions) AS impressions,
  SUM(clicks) AS clicks,
  NULL AS spend,
  NULL AS sessions,
  NULL AS conversions
FROM `demo-project.searchconsole_historical.sc_query_data`
WHERE data_date < DATE '2026-02-24'
GROUP BY data_date

UNION ALL

-- Search Console: organic search impressions and clicks (bulk export)
SELECT
  data_date AS date,
  'search_console' AS source,
  SUM(impressions) AS impressions,
  SUM(clicks) AS clicks,
  NULL AS spend,
  NULL AS sessions,
  NULL AS conversions
FROM `demo-project.searchconsole.searchdata_site_impression`
WHERE data_date >= DATE '2026-02-24'
GROUP BY data_date
