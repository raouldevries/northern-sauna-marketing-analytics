-- Unified campaign performance across Google Ads and Meta Ads.
--
-- Usage:
--   SELECT * FROM `demo-project.demo_data.v_campaign_performance`
--     WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
--   SELECT * FROM `demo-project.demo_data.v_campaign_performance`
--     WHERE platform = 'meta' AND spend > 10

CREATE OR REPLACE VIEW `demo-project.demo_data.v_campaign_performance` AS

-- Google Ads: join stats with campaign dimension for campaign_name
SELECT
  s.segments_date AS date,
  'google' AS platform,
  c.campaign_name,
  SUM(s.metrics_impressions) AS impressions,
  SUM(s.metrics_clicks) AS clicks,
  SUM(s.metrics_cost_micros) / 1e6 AS spend,
  SAFE_DIVIDE(SUM(s.metrics_clicks), SUM(s.metrics_impressions)) AS ctr,
  SAFE_DIVIDE(SUM(s.metrics_cost_micros) / 1e6, SUM(s.metrics_clicks)) AS cpc,
  COALESCE(SUM(s.metrics_conversions), 0) AS conversions,
  COALESCE(SUM(s.metrics_conversions_value), 0) AS conversion_value,
  NULL AS reach  -- Google Ads CampaignBasicStats does not include reach
FROM `demo-project.google_ads.ads_CampaignBasicStats_2079223948` s
JOIN `demo-project.google_ads.ads_Campaign_2079223948` c
  ON s.campaign_id = c.campaign_id
  AND c._DATA_DATE = c._LATEST_DATE
GROUP BY s.segments_date, c.campaign_name

UNION ALL

-- Meta Ads: extract purchase conversions from JSON actions/action_values arrays
-- actions[action_type="purchase"].value = conversion count
-- action_values[action_type="purchase"].value = conversion revenue (EUR)
SELECT
  i.date_start AS date,
  'meta' AS platform,
  i.campaign_name,
  SUM(i.impressions) AS impressions,
  SUM(i.clicks) AS clicks,
  SUM(CAST(i.spend AS FLOAT64)) AS spend,
  SAFE_DIVIDE(SUM(i.clicks), SUM(i.impressions)) AS ctr,
  SAFE_DIVIDE(SUM(CAST(i.spend AS FLOAT64)), SUM(i.clicks)) AS cpc,
  COALESCE(SUM(CAST(JSON_VALUE(a_conv, '$.value') AS FLOAT64)), 0) AS conversions,
  COALESCE(SUM(CAST(JSON_VALUE(a_val, '$.value') AS FLOAT64)), 0) AS conversion_value,
  SUM(i.reach) AS reach
FROM `demo-project.meta_ads.ads_insights` i
LEFT JOIN UNNEST(JSON_QUERY_ARRAY(i.actions)) AS a_conv
  ON JSON_VALUE(a_conv, '$.action_type') = 'purchase'
LEFT JOIN UNNEST(JSON_QUERY_ARRAY(i.action_values)) AS a_val
  ON JSON_VALUE(a_val, '$.action_type') = 'purchase'
GROUP BY i.date_start, i.campaign_name
