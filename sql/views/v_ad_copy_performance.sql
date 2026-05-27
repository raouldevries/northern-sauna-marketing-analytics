-- Ad copy performance: links creative text to daily ad-level metrics.
--
-- Creative text comes from `ad_creative_text` (populated by
-- scripts/sync_ad_creative_text.py via Meta Graph API) rather than
-- Airbyte's ad_creatives stream, which has poor JOIN coverage.
--
-- LEFT JOIN keeps all insight rows; copy fields are NULL for deleted ads.
--
-- Usage:
--   SELECT * FROM `demo-project.demo_data.v_ad_copy_performance`
--     WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
--   SELECT primary_text, headline, SUM(spend) AS total_spend
--     FROM `demo-project.demo_data.v_ad_copy_performance`
--     WHERE primary_text IS NOT NULL
--     GROUP BY 1, 2 ORDER BY total_spend DESC

CREATE OR REPLACE VIEW `demo-project.demo_data.v_ad_copy_performance` AS

SELECT
  i.date_start AS date,
  i.campaign_name,
  i.adset_name,
  i.ad_name,
  i.ad_id,
  t.creative_id,
  t.primary_text,
  t.headline,
  t.description,
  t.call_to_action_type,

  -- Performance metrics
  SUM(i.impressions) AS impressions,
  SUM(i.clicks) AS clicks,
  SUM(CAST(i.spend AS FLOAT64)) AS spend,
  SUM(i.reach) AS reach,
  SAFE_DIVIDE(SUM(i.clicks), SUM(i.impressions)) AS ctr,
  SAFE_DIVIDE(SUM(CAST(i.spend AS FLOAT64)), SUM(i.clicks)) AS cpc,

  -- Conversion extraction (same UNNEST pattern as v_campaign_performance.sql)
  COALESCE(SUM(CAST(JSON_VALUE(a_conv, '$.value') AS FLOAT64)), 0) AS conversions,
  COALESCE(SUM(CAST(JSON_VALUE(a_val, '$.value') AS FLOAT64)), 0) AS conversion_value

FROM `demo-project.meta_ads.ads_insights` i
-- LEFT JOIN ad_creative_text for copy (populated by sync_ad_creative_text.py)
LEFT JOIN `demo-project.meta_ads.ad_creative_text` t
  ON i.ad_id = t.ad_id
-- Conversion extraction via UNNEST (same pattern as v_campaign_performance.sql)
LEFT JOIN UNNEST(JSON_QUERY_ARRAY(i.actions)) AS a_conv
  ON JSON_VALUE(a_conv, '$.action_type') = 'purchase'
LEFT JOIN UNNEST(JSON_QUERY_ARRAY(i.action_values)) AS a_val
  ON JSON_VALUE(a_val, '$.action_type') = 'purchase'
GROUP BY
  i.date_start, i.campaign_name, i.adset_name, i.ad_name, i.ad_id,
  t.creative_id, t.primary_text, t.headline, t.description, t.call_to_action_type
