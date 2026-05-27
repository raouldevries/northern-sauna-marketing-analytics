-- Google Ads RSA asset performance: explodes RSA headline/description JSON
-- arrays into individual asset rows linked to daily ad-level metrics.
--
-- Each row = one asset (headline or description) × one ad × one date.
-- Preserves Google's assetPerformanceLabel and approval status from the
-- ads_Ad JSON, plus ad_strength and URL paths.
--
-- LIMITATION: metadata_metadata_performance_label comes from the ads_Ad dimension
-- table JSON, NOT from the authoritative ad_group_ad_asset_view feed.
-- Most values are PENDING or LEARNING. True BEST/GOOD/LOW labels will be
-- available after Step 3.3 adds the ad_group_ad_asset_view custom report.
--
-- WARNING: ad_impressions, ad_clicks, ad_spend, ad_conversions are at the
-- AD level, duplicated once per asset row. An ad with 15 headlines + 4
-- descriptions produces 19 rows, each carrying the SAME ad-level spend.
-- Never SUM ad_spend across assets of the same ad without deduplicating.
-- Safe patterns:
--   - Filter to a single field_type (HEADLINE or DESCRIPTION) first
--   - Use COUNT(DISTINCT ad_id) for counts
--   - Use v_google_ad_copy_performance for total spend aggregations
--
-- Scope: current ads only (_LATEST_DATE snapshot). If an ad's headlines
-- are edited, historical stats show against the current text, not the
-- text that was live on that date. Deleted ads are excluded entirely.
-- This matches the pattern used by v_google_ad_copy_performance.
--
-- Usage:
--   SELECT * FROM `demo-project.demo_data.v_google_rsa_asset_performance`
--     WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
--   SELECT asset_text, metadata_performance_label, COUNT(DISTINCT ad_id) AS ad_count
--     FROM `demo-project.demo_data.v_google_rsa_asset_performance`
--     WHERE field_type = 'HEADLINE'
--     GROUP BY 1, 2 ORDER BY ad_count DESC

CREATE OR REPLACE VIEW `demo-project.demo_data.v_google_rsa_asset_performance` AS

WITH rsa_assets AS (
  -- Unnest RSA headlines and descriptions into individual asset rows.
  -- Uses _LATEST_DATE snapshot: reflects current ad composition only.
  SELECT
    a.ad_group_ad_ad_id AS ad_id,
    a.ad_group_ad_ad_name AS ad_name,
    a.ad_group_ad_ad_strength AS ad_strength,
    a.ad_group_ad_ad_responsive_search_ad_path1 AS path1,
    a.ad_group_ad_ad_responsive_search_ad_path2 AS path2,
    a.ad_group_ad_ad_final_urls AS final_urls,
    a.ad_group_ad_status AS ad_status,
    a.ad_group_id,
    a.campaign_id,
    'HEADLINE' AS field_type,
    JSON_VALUE(h, '$.text') AS asset_text,
    JSON_VALUE(h, '$.assetPerformanceLabel') AS metadata_performance_label,
    JSON_VALUE(h, '$.policySummaryInfo.approvalStatus') AS approval_status
  FROM `demo-project.google_ads.ads_Ad_2079223948` a,
    UNNEST(JSON_QUERY_ARRAY(a.ad_group_ad_ad_responsive_search_ad_headlines)) AS h
  WHERE a._DATA_DATE = a._LATEST_DATE
    AND a.ad_group_ad_ad_type = 'RESPONSIVE_SEARCH_AD'

  UNION ALL

  SELECT
    a.ad_group_ad_ad_id AS ad_id,
    a.ad_group_ad_ad_name AS ad_name,
    a.ad_group_ad_ad_strength AS ad_strength,
    a.ad_group_ad_ad_responsive_search_ad_path1 AS path1,
    a.ad_group_ad_ad_responsive_search_ad_path2 AS path2,
    a.ad_group_ad_ad_final_urls AS final_urls,
    a.ad_group_ad_status AS ad_status,
    a.ad_group_id,
    a.campaign_id,
    'DESCRIPTION' AS field_type,
    JSON_VALUE(d, '$.text') AS asset_text,
    JSON_VALUE(d, '$.assetPerformanceLabel') AS metadata_performance_label,
    JSON_VALUE(d, '$.policySummaryInfo.approvalStatus') AS approval_status
  FROM `demo-project.google_ads.ads_Ad_2079223948` a,
    UNNEST(JSON_QUERY_ARRAY(a.ad_group_ad_ad_responsive_search_ad_descriptions)) AS d
  WHERE a._DATA_DATE = a._LATEST_DATE
    AND a.ad_group_ad_ad_type = 'RESPONSIVE_SEARCH_AD'
)

SELECT
  s.segments_date AS date,
  c.campaign_name,
  ag.ad_group_name,
  ra.ad_id,
  ra.ad_name,
  ra.ad_status,
  ra.ad_strength,
  ra.field_type,
  ra.asset_text,
  ra.metadata_performance_label,
  ra.approval_status,
  ra.path1,
  ra.path2,
  ra.final_urls,

  -- Ad-level metrics (duplicated per asset row — see header WARNING)
  COALESCE(SUM(s.metrics_impressions), 0) AS ad_impressions,
  COALESCE(SUM(s.metrics_clicks), 0) AS ad_clicks,
  COALESCE(SUM(s.metrics_cost_micros), 0) / 1e6 AS ad_spend,
  SAFE_DIVIDE(SUM(s.metrics_clicks), SUM(s.metrics_impressions)) AS ad_ctr,
  SAFE_DIVIDE(SUM(s.metrics_cost_micros) / 1e6, SUM(s.metrics_clicks)) AS ad_cpc,
  COALESCE(SUM(s.metrics_conversions), 0) AS ad_conversions,
  COALESCE(SUM(s.metrics_conversions_value), 0) AS ad_conversion_value

FROM rsa_assets ra
-- LEFT JOIN: preserves ads with zero impressions (paused, new, low budget)
LEFT JOIN `demo-project.google_ads.ads_AdBasicStats_2079223948` s
  ON ra.ad_id = s.ad_group_ad_ad_id
  -- No _DATA_DATE filter: AdBasicStats is a daily facts table, all dates included
LEFT JOIN `demo-project.google_ads.ads_Campaign_2079223948` c
  ON ra.campaign_id = c.campaign_id
  AND c._DATA_DATE = c._LATEST_DATE
LEFT JOIN `demo-project.google_ads.ads_AdGroup_2079223948` ag
  ON ra.ad_group_id = ag.ad_group_id
  AND ag._DATA_DATE = ag._LATEST_DATE
GROUP BY
  s.segments_date, c.campaign_name, ag.ad_group_name,
  ra.ad_id, ra.ad_name, ra.ad_status, ra.ad_strength,
  ra.field_type, ra.asset_text, ra.metadata_performance_label, ra.approval_status,
  ra.path1, ra.path2, ra.final_urls
