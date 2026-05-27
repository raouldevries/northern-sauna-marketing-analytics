-- Google Ads video performance: joins video stats tables for complete
-- Demand Gen video creative metrics including retention quartiles.
--
-- Combines VideoBasicStats (clicks, impressions, cost, conversions) with
-- VideoNonClickStats (TrueView views, quartile retention, engagement) and
-- Video metadata (title, duration).
--
-- Note: For Demand Gen campaigns, the "trueview" metric variants contain
-- the actual data (metrics_video_views is NULL for these campaign types).
--
-- Rates (p25-p100, view_rate, engagement_rate) are impression-weighted
-- averages across device/network segments for accurate rollup.
--
-- Usage:
--   SELECT * FROM `demo-project.demo_data.v_google_video_performance`
--     WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
--   SELECT video_title, SUM(spend) AS total_spend, AVG(view_rate) AS avg_view_rate
--     FROM `demo-project.demo_data.v_google_video_performance`
--     GROUP BY 1 ORDER BY total_spend DESC

CREATE OR REPLACE VIEW `demo-project.demo_data.v_google_video_performance` AS

WITH segment_joined AS (
  -- Join BasicStats and NonClickStats at their shared lower grain
  -- (video_id, campaign_id, date, ad_id, device, network) to enable
  -- impression-weighted aggregation of rate metrics.
  SELECT
    b.video_id,
    b.campaign_id,
    b.segments_date,
    b.metrics_impressions AS impressions,
    b.metrics_clicks AS clicks,
    b.metrics_cost_micros / 1e6 AS spend,
    COALESCE(b.metrics_conversions, 0) AS conversions,
    COALESCE(b.metrics_conversions_value, 0) AS conversion_value,
    COALESCE(b.metrics_view_through_conversions, 0) AS view_through_conversions,
    -- TrueView metrics (standard metrics_video_views is NULL for Demand Gen)
    COALESCE(nc.metrics_video_trueview_views, 0) AS video_views,
    COALESCE(nc.metrics_engagements, 0) AS engagements,
    nc.metrics_video_trueview_view_rate AS view_rate,
    nc.metrics_video_quartile_p25_rate AS p25_rate,
    nc.metrics_video_quartile_p50_rate AS p50_rate,
    nc.metrics_video_quartile_p75_rate AS p75_rate,
    nc.metrics_video_quartile_p100_rate AS p100_rate,
    nc.metrics_engagement_rate AS engagement_rate,
    nc.metrics_trueview_average_cpv AS avg_cpv_micros
  FROM `demo-project.google_ads.ads_VideoBasicStats_2079223948` b
  LEFT JOIN `demo-project.google_ads.ads_VideoNonClickStats_2079223948` nc
    ON b.video_id = nc.video_id
    AND b.campaign_id = nc.campaign_id
    AND b.segments_date = nc.segments_date
    AND b.ad_group_ad_ad_id = nc.ad_group_ad_ad_id
    AND b.segments_device = nc.segments_device
    AND b.segments_ad_network_type = nc.segments_ad_network_type
),

-- Aggregate to video × campaign × date grain with impression-weighted rates
aggregated AS (
  SELECT
    video_id,
    campaign_id,
    segments_date,
    SUM(impressions) AS impressions,
    SUM(clicks) AS clicks,
    SUM(spend) AS spend,
    SUM(conversions) AS conversions,
    SUM(conversion_value) AS conversion_value,
    SUM(view_through_conversions) AS view_through_conversions,
    SUM(video_views) AS video_views,
    SUM(engagements) AS engagements,
    -- Impression-weighted rates
    SAFE_DIVIDE(SUM(view_rate * impressions), SUM(impressions)) AS view_rate,
    SAFE_DIVIDE(SUM(p25_rate * impressions), SUM(impressions)) AS p25_rate,
    SAFE_DIVIDE(SUM(p50_rate * impressions), SUM(impressions)) AS p50_rate,
    SAFE_DIVIDE(SUM(p75_rate * impressions), SUM(impressions)) AS p75_rate,
    SAFE_DIVIDE(SUM(p100_rate * impressions), SUM(impressions)) AS p100_rate,
    SAFE_DIVIDE(SUM(engagement_rate * impressions), SUM(impressions)) AS engagement_rate,
    -- View-weighted CPV (micros → EUR)
    SAFE_DIVIDE(SUM(avg_cpv_micros * video_views), SUM(video_views)) / 1e6 AS avg_cpv
  FROM segment_joined
  GROUP BY video_id, campaign_id, segments_date
),

-- Deduplicate Video metadata (same video can appear in multiple ad groups)
video_meta AS (
  SELECT video_id, ANY_VALUE(video_title) AS video_title,
         ANY_VALUE(video_duration_millis) AS video_duration_millis
  FROM `demo-project.google_ads.ads_Video_2079223948`
  WHERE _DATA_DATE = _LATEST_DATE
  GROUP BY video_id
)

SELECT
  a.video_id,
  v.video_title,
  v.video_duration_millis,
  a.segments_date AS date,
  c.campaign_name,

  -- Basic metrics
  a.impressions,
  a.clicks,
  a.spend,
  a.conversions,
  a.conversion_value,
  a.view_through_conversions,

  -- Video-specific metrics
  a.video_views,
  a.view_rate,
  a.p25_rate,
  a.p50_rate,
  a.p75_rate,
  a.p100_rate,
  a.engagements,
  a.engagement_rate,
  a.avg_cpv,

  -- Derived metrics
  SAFE_DIVIDE(a.clicks, a.impressions) AS ctr,
  SAFE_DIVIDE(a.spend, a.clicks) AS cpc,
  SAFE_DIVIDE(a.spend, a.video_views) AS cost_per_view,
  SAFE_DIVIDE(a.spend, a.conversions) AS cpa

FROM aggregated a
LEFT JOIN video_meta v
  ON a.video_id = v.video_id
LEFT JOIN `demo-project.google_ads.ads_Campaign_2079223948` c
  ON a.campaign_id = c.campaign_id
  AND c._DATA_DATE = c._LATEST_DATE
