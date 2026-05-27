-- Google Ads ad copy performance: links creative text to daily ad-level metrics.
--
-- Extracts headlines and descriptions from RSA, Responsive Display, and
-- Dynamic Search ads.  Demand Gen Video ads have no creative text columns
-- in the Data Transfer — only ad_name is available for those.
--
-- Usage:
--   SELECT * FROM `demo-project.demo_data.v_google_ad_copy_performance`
--     WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
--   SELECT headlines, descriptions, SUM(spend) AS total_spend
--     FROM `demo-project.demo_data.v_google_ad_copy_performance`
--     WHERE headlines IS NOT NULL
--     GROUP BY 1, 2 ORDER BY total_spend DESC

CREATE OR REPLACE VIEW `demo-project.demo_data.v_google_ad_copy_performance` AS

SELECT
  s.segments_date AS date,
  c.campaign_name,
  ag.ad_group_name,
  a.ad_group_ad_ad_name AS ad_name,
  a.ad_group_ad_ad_id AS ad_id,
  a.ad_group_ad_ad_type AS ad_type,

  -- Headlines: RSA → Display → NULL (DSA/Video have no headline columns)
  COALESCE(
    NULLIF(
      ARRAY_TO_STRING(
        ARRAY(SELECT JSON_VALUE(h, '$.text')
              FROM UNNEST(JSON_QUERY_ARRAY(a.ad_group_ad_ad_responsive_search_ad_headlines)) h),
        ' | '
      ), ''
    ),
    NULLIF(
      ARRAY_TO_STRING(
        ARRAY(SELECT JSON_VALUE(h, '$.text')
              FROM UNNEST(JSON_QUERY_ARRAY(a.ad_group_ad_ad_responsive_display_ad_headlines)) h),
        ' | '
      ), ''
    )
  ) AS headlines,

  -- Descriptions: RSA → Display → DSA (scalar strings, not JSON arrays) → NULL
  COALESCE(
    NULLIF(
      ARRAY_TO_STRING(
        ARRAY(SELECT JSON_VALUE(d, '$.text')
              FROM UNNEST(JSON_QUERY_ARRAY(a.ad_group_ad_ad_responsive_search_ad_descriptions)) d),
        ' | '
      ), ''
    ),
    NULLIF(
      ARRAY_TO_STRING(
        ARRAY(SELECT JSON_VALUE(d, '$.text')
              FROM UNNEST(JSON_QUERY_ARRAY(a.ad_group_ad_ad_responsive_display_ad_descriptions)) d),
        ' | '
      ), ''
    ),
    NULLIF(
      ARRAY_TO_STRING(
        ARRAY(
          SELECT x FROM UNNEST([
            a.ad_group_ad_ad_expanded_dynamic_search_ad_description,
            a.ad_group_ad_ad_expanded_dynamic_search_ad_description2
          ]) AS x
          WHERE x IS NOT NULL
        ),
        ' | '
      ), ''
    )
  ) AS descriptions,

  -- Performance metrics
  SUM(s.metrics_impressions) AS impressions,
  SUM(s.metrics_clicks) AS clicks,
  SUM(s.metrics_cost_micros) / 1e6 AS spend,
  SAFE_DIVIDE(SUM(s.metrics_clicks), SUM(s.metrics_impressions)) AS ctr,
  SAFE_DIVIDE(SUM(s.metrics_cost_micros) / 1e6, SUM(s.metrics_clicks)) AS cpc,
  COALESCE(SUM(s.metrics_conversions), 0) AS conversions,
  COALESCE(SUM(s.metrics_conversions_value), 0) AS conversion_value

FROM `demo-project.google_ads.ads_AdBasicStats_2079223948` s
LEFT JOIN `demo-project.google_ads.ads_Ad_2079223948` a
  ON s.ad_group_ad_ad_id = a.ad_group_ad_ad_id
  AND a._DATA_DATE = a._LATEST_DATE
LEFT JOIN `demo-project.google_ads.ads_Campaign_2079223948` c
  ON s.campaign_id = c.campaign_id
  AND c._DATA_DATE = c._LATEST_DATE
LEFT JOIN `demo-project.google_ads.ads_AdGroup_2079223948` ag
  ON s.ad_group_id = ag.ad_group_id
  AND ag._DATA_DATE = ag._LATEST_DATE
GROUP BY
  s.segments_date, c.campaign_name, ag.ad_group_name,
  a.ad_group_ad_ad_name, a.ad_group_ad_ad_id, a.ad_group_ad_ad_type,
  headlines, descriptions
