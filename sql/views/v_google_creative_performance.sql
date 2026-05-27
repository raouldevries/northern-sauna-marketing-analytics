-- Unified Google Ads creative performance: per-asset daily metrics across
-- PMax, Search (RSA + campaign-level image extensions), and Demand Gen video.
--
-- Four source branches (UNION ALL):
--   1. PMax: AssetGroupAssetMetrics → AssetMetadata → AssetGroupMetrics → Campaign
--   2. Search RSA ad-level: AdGroupAdAssetViewMetrics → AssetMetadata → AdGroup → Campaign
--   3. Search campaign image extensions: CampaignAssetStats → AssetMetadata → Campaign
--   4. Demand Gen Video: v_google_video_performance (already aggregated)
--
-- STDC phase comes from the priority logic in
-- streamlit/features/marketing/stdc.py / constants.py.
-- The `location` column is the campaign's marketing concept (e.g.
-- 'Stockholm Waterfront', 'Waterside', 'Stockholm Waterfront'): emitted when
-- exactly one concept matches the campaign name, NULL when zero or
-- two-plus concepts match. For weighted multi-location attribution
-- use v_location_performance.
--
-- ⚠  ASSET-ATTRIBUTED, NOT ADDITIVE
-- Each row is one asset's attributed contribution on one day. A single ad
-- impression is counted once per asset that rendered with it, so
-- SUM(spend) / SUM(impressions) across rows is NOT a valid channel total —
-- summing across rows double-counts the underlying ad. Use this view for
-- asset-level ranking and comparison. For channel-total spend or
-- impressions, use `v_campaign_performance` or `p_ads_CampaignBasicStats_2079223948`.
--
-- Example usage (asset ranking, the intended pattern):
--   -- Top image creatives by conversions, last 14 days
--   SELECT campaign_name, image_url, asset_name,
--          SUM(impressions) AS impressions, SUM(clicks) AS clicks,
--          SUM(conversions) AS conversions
--   FROM `demo-project.demo_data.v_google_creative_performance`
--   WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
--     AND asset_type = 'IMAGE'
--   GROUP BY campaign_name, image_url, asset_name
--   ORDER BY conversions DESC LIMIT 20;
--
--   -- Top RSA headlines by CTR (text-asset rows have asset_text populated)
--   SELECT asset_text,
--          SUM(impressions) AS impressions, SUM(clicks) AS clicks,
--          SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr
--   FROM `demo-project.demo_data.v_google_creative_performance`
--   WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
--     AND campaign_type = 'SEARCH' AND asset_type = 'TEXT'
--   GROUP BY asset_text
--   HAVING SUM(impressions) >= 100
--   ORDER BY ctr DESC LIMIT 20;

CREATE OR REPLACE VIEW `demo-project.demo_data.v_google_creative_performance` AS

-- ============================================================
-- Branch 1: PMax assets (from custom GAQL report)
-- ============================================================
WITH pmax_assets AS (
  SELECT
    aga.segments_date AS date,
    'PERFORMANCE_MAX' AS campaign_type,
    c.campaign_name,
    agm.asset_group_name,
    agm.asset_group_ad_strength AS ad_strength,  -- Asset group level, not per-asset
    aga.asset_group_asset_field_type AS field_type,
    -- Asset content from metadata
    am.asset_type,
    am.asset_text_asset_text AS asset_text,
    am.asset_image_asset_full_size_url AS image_url,
    am.asset_youtube_video_asset_youtube_video_id AS youtube_video_id,
    am.asset_name,
    -- Metrics
    aga.metrics_impressions AS impressions,
    aga.metrics_clicks AS clicks,
    aga.metrics_cost_micros / 1e6 AS spend,
    COALESCE(aga.metrics_conversions, 0) AS conversions,
    COALESCE(aga.metrics_conversions_value, 0) AS conversion_value,
    -- No video-specific metrics for PMax
    CAST(NULL AS INT64) AS video_views,
    CAST(NULL AS FLOAT64) AS view_rate,
    CAST(NULL AS FLOAT64) AS p25_rate,
    CAST(NULL AS FLOAT64) AS p50_rate,
    CAST(NULL AS FLOAT64) AS p75_rate,
    CAST(NULL AS FLOAT64) AS p100_rate
  -- PMax asset + metadata tables are populated by the northern_sauna-google-ads-pmax-creative
  -- custom transfer into the `google_ads_pmax` dataset (separate from the main
  -- `google_ads` transfer). See CLAUDE.md for why the split exists.
  FROM `demo-project.google_ads_pmax.ads_AssetGroupAssetMetrics_2079223948` aga
  LEFT JOIN `demo-project.google_ads_pmax.ads_AssetMetadata_2079223948` am
    ON CAST(REGEXP_EXTRACT(aga.asset_group_asset_asset, r'/assets/(\d+)') AS INT64) = am.asset_id
    AND am._DATA_DATE = am._LATEST_DATE
  -- AssetGroupMetrics is a daily fact table (segments_date scoped); date match prevents fan-out
  LEFT JOIN `demo-project.google_ads_pmax.ads_AssetGroupMetrics_2079223948` agm
    ON aga.asset_group_id = agm.asset_group_id
    AND aga.campaign_id = agm.campaign_id
    AND aga.segments_date = agm.segments_date
  -- ads_Campaign is populated by the main google_ads transfer, not the custom one
  LEFT JOIN `demo-project.google_ads.ads_Campaign_2079223948` c
    ON aga.campaign_id = c.campaign_id
    AND c._DATA_DATE = c._LATEST_DATE
),

-- ============================================================
-- Branch 2: Search RSA assets (from custom GAQL report)
-- ============================================================
rsa_assets AS (
  SELECT
    aav.segments_date AS date,
    'SEARCH' AS campaign_type,
    c.campaign_name,
    CAST(NULL AS STRING) AS asset_group_name,
    CAST(NULL AS STRING) AS ad_strength,
    aav.ad_group_ad_asset_view_field_type AS field_type,
    am.asset_type,
    am.asset_text_asset_text AS asset_text,
    am.asset_image_asset_full_size_url AS image_url,
    am.asset_youtube_video_asset_youtube_video_id AS youtube_video_id,
    am.asset_name,
    aav.metrics_impressions AS impressions,
    aav.metrics_clicks AS clicks,
    aav.metrics_cost_micros / 1e6 AS spend,
    COALESCE(aav.metrics_conversions, 0) AS conversions,
    -- AdGroupAdAssetViewMetrics does not include conversions_value
    CAST(0 AS FLOAT64) AS conversion_value,
    CAST(NULL AS INT64) AS video_views,
    CAST(NULL AS FLOAT64) AS view_rate,
    CAST(NULL AS FLOAT64) AS p25_rate,
    CAST(NULL AS FLOAT64) AS p50_rate,
    CAST(NULL AS FLOAT64) AS p75_rate,
    CAST(NULL AS FLOAT64) AS p100_rate
  -- RSA asset-level metrics + metadata come from the google_ads_pmax dataset
  -- (same custom transfer as PMax assets). ads_AdGroup and ads_Campaign remain
  -- in google_ads (main transfer).
  FROM `demo-project.google_ads_pmax.ads_AdGroupAdAssetViewMetrics_2079223948` aav
  LEFT JOIN `demo-project.google_ads_pmax.ads_AssetMetadata_2079223948` am
    ON CAST(REGEXP_EXTRACT(aav.ad_group_ad_asset_view_asset, r'/assets/(\d+)') AS INT64) = am.asset_id
    AND am._DATA_DATE = am._LATEST_DATE
  -- AdGroupAdAssetViewMetrics has no campaign_id; reach campaign via ad_group → campaign
  LEFT JOIN `demo-project.google_ads.ads_AdGroup_2079223948` ag
    ON aav.ad_group_id = ag.ad_group_id
    AND ag._DATA_DATE = ag._LATEST_DATE
  LEFT JOIN `demo-project.google_ads.ads_Campaign_2079223948` c
    ON ag.campaign_id = c.campaign_id
    AND c._DATA_DATE = c._LATEST_DATE
),

-- ============================================================
-- Branch 3: Search campaign image extensions (AD_IMAGE)
-- ads_CampaignAssetStats_2079223948 (populated by the main google_ads
-- transfer) exposes daily metrics for assets attached at the campaign
-- level. We want only SEARCH campaigns' AD_IMAGE extensions — PMax
-- shares this table so the channel guard on campaign.channel_type is
-- critical. Asset type/URL come from the same AssetMetadata lookup
-- used by Branches 1 & 2. Rows are aggregated across device /
-- ad_network_type to match the (date × campaign × asset) grain of
-- the other branches.
-- ============================================================
search_campaign_image_assets AS (
  SELECT
    cas.segments_date AS date,
    'SEARCH' AS campaign_type,
    c.campaign_name,
    CAST(NULL AS STRING) AS asset_group_name,
    CAST(NULL AS STRING) AS ad_strength,
    cas.campaign_asset_field_type AS field_type,
    am.asset_type,
    am.asset_text_asset_text AS asset_text,
    am.asset_image_asset_full_size_url AS image_url,
    am.asset_youtube_video_asset_youtube_video_id AS youtube_video_id,
    am.asset_name,
    SUM(cas.metrics_impressions) AS impressions,
    SUM(cas.metrics_clicks) AS clicks,
    SUM(cas.metrics_cost_micros) / 1e6 AS spend,
    COALESCE(SUM(cas.metrics_conversions), 0) AS conversions,
    COALESCE(SUM(cas.metrics_conversions_value), 0) AS conversion_value,
    CAST(NULL AS INT64) AS video_views,
    CAST(NULL AS FLOAT64) AS view_rate,
    CAST(NULL AS FLOAT64) AS p25_rate,
    CAST(NULL AS FLOAT64) AS p50_rate,
    CAST(NULL AS FLOAT64) AS p75_rate,
    CAST(NULL AS FLOAT64) AS p100_rate
  FROM `demo-project.google_ads.ads_CampaignAssetStats_2079223948` cas
  -- Channel guard (INNER JOIN): excludes PMax / Display / other rows that share this table.
  INNER JOIN `demo-project.google_ads.ads_Campaign_2079223948` c
    ON CAST(REGEXP_EXTRACT(cas.campaign_asset_campaign, r'/campaigns/(\d+)') AS INT64) = c.campaign_id
    AND c._DATA_DATE = c._LATEST_DATE
    AND c.campaign_advertising_channel_type = 'SEARCH'
  LEFT JOIN `demo-project.google_ads_pmax.ads_AssetMetadata_2079223948` am
    ON CAST(REGEXP_EXTRACT(cas.campaign_asset_asset, r'/assets/(\d+)') AS INT64) = am.asset_id
    AND am._DATA_DATE = am._LATEST_DATE
  WHERE cas.campaign_asset_field_type = 'AD_IMAGE'
  GROUP BY
    cas.segments_date, c.campaign_name, cas.campaign_asset_field_type,
    am.asset_type, am.asset_text_asset_text, am.asset_image_asset_full_size_url,
    am.asset_youtube_video_asset_youtube_video_id, am.asset_name
),

-- ============================================================
-- Branch 4: Demand Gen Video (from existing video view)
-- v_google_video_performance is already aggregated to
-- (date, video_id, campaign_name) — no re-aggregation here.
-- ============================================================
video_assets AS (
  SELECT
    vp.date,
    'DEMAND_GEN' AS campaign_type,
    vp.campaign_name,
    CAST(NULL AS STRING) AS asset_group_name,
    CAST(NULL AS STRING) AS ad_strength,
    'YOUTUBE_VIDEO' AS field_type,
    'YOUTUBE_VIDEO' AS asset_type,
    CAST(NULL AS STRING) AS asset_text,
    CAST(NULL AS STRING) AS image_url,
    vp.video_id AS youtube_video_id,
    vp.video_title AS asset_name,
    vp.impressions,
    vp.clicks,
    vp.spend,
    vp.conversions,
    vp.conversion_value,
    vp.video_views,
    vp.view_rate,
    vp.p25_rate,
    vp.p50_rate,
    vp.p75_rate,
    vp.p100_rate
  FROM `demo-project.demo_data.v_google_video_performance` vp
),

-- ============================================================
-- Combine all branches
-- ============================================================
combined AS (
  SELECT * FROM pmax_assets
  UNION ALL
  SELECT * FROM rsa_assets
  UNION ALL
  SELECT * FROM search_campaign_image_assets
  UNION ALL
  SELECT * FROM video_assets
),

-- ============================================================
-- Concept detection (Google-only, post-rename explicit-first).
-- Mirrors the Google branch of v_location_performance: pattern
-- map, raw matches, then cluster-override resolution. Bare
-- 'kamppi' covers the "Helsinki Kallio + Kamppi"
-- legacy form still observed in live Google names. No bare
-- city catch-alls (Stockholm/Helsinki/Oslo).
-- ============================================================
google_concept_map AS (
  SELECT pattern, concept FROM UNNEST([
    STRUCT('stockholm waterfront' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('stockholm ij' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('stockholm stockholm' AS pattern, 'Stockholm North' AS concept),
    STRUCT('stockholm waterside' AS pattern, 'Waterside' AS concept),
    -- Pier books under the same Bookeo venue as Stockholm Waterfront; route the
    -- pattern into the Stockholm Waterfront concept so the creative-level label
    -- stays consistent with v_location_performance.
    STRUCT('stockholm pier' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('helsinki kallio' AS pattern, 'Helsinki Kallio' AS concept),
    STRUCT('helsinki kamppi' AS pattern, 'Helsinki Kamppi' AS concept),
    STRUCT('kamppi' AS pattern, 'Helsinki Kamppi' AS concept),
    STRUCT('oslo frogner' AS pattern, 'Oslo Frogner' AS concept),
    STRUCT('oslo grünerløkka' AS pattern, 'Oslo Grünerløkka' AS concept),
    STRUCT('seaside-1' AS pattern, 'Seaside 1' AS concept),
    STRUCT('seaside-2' AS pattern, 'Seaside 2' AS concept),
    STRUCT('seaside-3' AS pattern, 'Seaside 3' AS concept),
    STRUCT('seaside-4' AS pattern, 'Seaside 4' AS concept),
    STRUCT('bergen aan zee' AS pattern, 'Bergen aan Zee' AS concept),
    STRUCT('breda' AS pattern, 'Breda' AS concept),
    STRUCT('inland-1' AS pattern, 'Inland 1' AS concept),
    -- Legacy single-token forms preserved for label parity with
    -- the previous view (asset rankings still group by 'Östermalm' / 'Södermalm').
    STRUCT('östermalm' AS pattern, 'Östermalm' AS concept),
    STRUCT('östermalm' AS pattern, 'Östermalm' AS concept),
    STRUCT('södermalm' AS pattern, 'Södermalm' AS concept)
  ])
),

cluster_overrides AS (
  SELECT cluster, child FROM UNNEST([
    -- Östermalm/Södermalm override Stockholm Waterfront (legacy rule).
    STRUCT('Stockholm Waterfront' AS cluster, 'Östermalm' AS child),
    STRUCT('Stockholm Waterfront' AS cluster, 'Södermalm' AS child)
  ])
),

google_concepts_raw AS (
  SELECT DISTINCT
    c.campaign_name,
    cm.concept
  FROM (SELECT DISTINCT campaign_name FROM combined WHERE campaign_name IS NOT NULL) c
  CROSS JOIN google_concept_map cm
  WHERE STRPOS(LOWER(c.campaign_name), cm.pattern) > 0
),

-- LEFT JOIN anti-join form (BigQuery cannot de-correlate the
-- equivalent NOT EXISTS at plan time when the source row count is
-- modest, even though it passes dry-run parsing).
google_concepts_resolved AS (
  SELECT r.campaign_name, r.concept
  FROM google_concepts_raw r
  LEFT JOIN cluster_overrides o ON o.cluster = r.concept
  LEFT JOIN google_concepts_raw r2
    ON r2.campaign_name = r.campaign_name
    AND r2.concept = o.child
  GROUP BY r.campaign_name, r.concept
  HAVING SUM(IF(r2.concept IS NOT NULL, 1, 0)) = 0
),

-- One row per campaign_name: concept if exactly one match, NULL otherwise.
campaign_location AS (
  SELECT
    campaign_name,
    CASE WHEN COUNT(*) = 1 THEN ANY_VALUE(concept) ELSE NULL END AS location
  FROM google_concepts_resolved
  GROUP BY campaign_name
)

SELECT
  c.*,

  -- STDC phase (matches stdc.py priority logic from constants.py)
  CASE
    -- Priority 1: Search or PMax → DO
    WHEN LOWER(c.campaign_name) LIKE '%| s |%'
      OR LOWER(c.campaign_name) LIKE '%| pm |%' THEN 'DO'
    -- Priority 2: Remarketing → CARE
    WHEN LOWER(c.campaign_name) LIKE '%retargeting%'
      OR LOWER(c.campaign_name) LIKE '%remarketing%'
      OR LOWER(c.campaign_name) LIKE '%| rm |%'
      OR LOWER(c.campaign_name) LIKE '%loyalty%'
      OR LOWER(c.campaign_name) LIKE '%care%' THEN 'CARE'
    -- Priority 3: Conversion keywords → DO
    WHEN LOWER(c.campaign_name) LIKE '%conversions%'
      OR LOWER(c.campaign_name) LIKE '%conversion%'
      OR LOWER(c.campaign_name) LIKE '%purchase%' THEN 'DO'
    -- Priority 4: Awareness → SEE
    WHEN LOWER(c.campaign_name) LIKE '%demand gen%'
      OR LOWER(c.campaign_name) LIKE '%display%'
      OR LOWER(c.campaign_name) LIKE '%reach%'
      OR LOWER(c.campaign_name) LIKE '%awareness%'
      OR LOWER(c.campaign_name) LIKE '%| see%' THEN 'SEE'
    -- Priority 5: Consideration → THINK
    WHEN LOWER(c.campaign_name) LIKE '%non-branded%'
      OR LOWER(c.campaign_name) LIKE '%non branded%' THEN 'THINK'
    ELSE 'Untagged'
  END AS stdc_phase,

  -- Concept-level location: emits the marketing concept (e.g.
  -- 'Stockholm Waterfront', 'Waterside', 'Östermalm') when exactly
  -- one concept matches the campaign name; NULL when zero or
  -- two-plus concepts match. Matches the labels used by the
  -- previous longest-match logic for the values that survived the
  -- rewrite (Östermalm, Södermalm, Waterside, Stockholm Waterfront, Stockholm
  -- Stockholm, Oslo Grünerløkka, Oslo Frogner, Helsinki Kallio,
  -- Helsinki Kamppi, Seaside 1, Inland 1, Seaside 2, Wijk
  -- aan Zee, Seaside 4, Bergen aan Zee, Breda). New emission
  -- value: 'Stockholm Waterfront'. The 'stockholm pier'
  -- pattern routes into the 'Stockholm Waterfront' concept because Pier
  -- books under the same Bookeo venue. Removed bare city buckets:
  -- 'Stockholm', 'Helsinki', 'Oslo'.
  cl.location,

  -- Derived metrics
  SAFE_DIVIDE(c.clicks, c.impressions) AS ctr,
  SAFE_DIVIDE(c.spend, c.clicks) AS cpc,
  SAFE_DIVIDE(c.spend, c.conversions) AS cpa,
  SAFE_DIVIDE(c.conversion_value, c.spend) AS roas

FROM combined c
LEFT JOIN campaign_location cl ON c.campaign_name = cl.campaign_name
