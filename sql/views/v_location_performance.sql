-- Location-level performance combining bookings with marketing metrics.
-- Concept-based weighted allocation:
--   1. Detect all marketing concepts mentioned in each campaign (Google) or
--      ad-set (Meta).
--   2. Drop a cluster concept when one of its specific child concepts is
--      also matched (e.g. Östermalm/Södermalm override Stockholm Waterfront;
--      Helsinki Kallio overrides Helsinki City).
--   3. Split spend evenly across the surviving concepts (1/N), then expand
--      each concept to one or more booking locations via sub-weights that
--      sum to 1.0 per concept.
-- See plans/weighted-location-allocation-plan.md for the full spec.
--
-- Usage:
--   SELECT * FROM `demo-project.demo_data.v_location_performance`
--     WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

CREATE OR REPLACE VIEW `demo-project.demo_data.v_location_performance` AS

WITH
-- ============================================================
-- Google concept patterns (explicit-first; the campaigns were
-- renamed in 2026-05 to use full concept phrases). Bare-token
-- patterns are added only for legacy forms still observed in
-- live Google names.
-- ============================================================
google_concept_map AS (
  SELECT pattern, concept FROM UNNEST([
    STRUCT('stockholm waterfront' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('stockholm ij' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('stockholm stockholm' AS pattern, 'Stockholm North' AS concept),
    STRUCT('stockholm waterside' AS pattern, 'Stockholm Waterfront' AS concept),
    -- Pier is operationally the same Bookeo venue as Stockholm Waterfront; route
    -- any explicit Pier mention into the Stockholm Waterfront concept.
    STRUCT('stockholm pier' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('helsinki kallio' AS pattern, 'Helsinki Kallio' AS concept),
    STRUCT('helsinki kamppi' AS pattern, 'Helsinki Kamppi' AS concept),
    -- Bare 'kamppi' for "Helsinki Kallio + Kamppi" multi-location campaigns.
    STRUCT('kamppi' AS pattern, 'Helsinki Kamppi' AS concept),
    STRUCT('oslo frogner' AS pattern, 'Oslo Frogner' AS concept),
    STRUCT('oslo grünerløkka' AS pattern, 'Oslo Grünerløkka' AS concept),
    STRUCT('seaside-1' AS pattern, 'Seaside 1' AS concept),
    STRUCT('seaside-2' AS pattern, 'Seaside 2' AS concept),
    STRUCT('seaside-3' AS pattern, 'Seaside 3' AS concept),
    STRUCT('seaside-4' AS pattern, 'Seaside 4' AS concept),
    STRUCT('bergen aan zee' AS pattern, 'Bergen aan Zee' AS concept),
    STRUCT('breda' AS pattern, 'Breda' AS concept),
    STRUCT('inland-1' AS pattern, 'Inland 1' AS concept)
  ])
),

-- ============================================================
-- Meta concept patterns. Meta names were not renamed, so this
-- map is broader: legacy Waterfront synonyms, ad-set-level
-- cluster patterns, and bare specific tokens for ad-set names
-- that mention a sauna inside a cluster name.
-- ============================================================
meta_concept_map AS (
  SELECT pattern, concept FROM UNNEST([
    -- Single-location concepts (prefixed forms in Meta campaign names).
    STRUCT('stockholm ij' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('stockholm stockholm' AS pattern, 'Stockholm North' AS concept),
    STRUCT('stockholm waterside' AS pattern, 'Stockholm Waterfront' AS concept),
    -- Pier is operationally the same Bookeo venue as Stockholm Waterfront; both
    -- the prefixed and bare forms route into the Stockholm Waterfront concept.
    STRUCT('stockholm pier' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('pier' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('helsinki kallio' AS pattern, 'Helsinki Kallio' AS concept),
    STRUCT('helsinki kamppi' AS pattern, 'Helsinki Kamppi' AS concept),
    STRUCT('oslo frogner' AS pattern, 'Oslo Frogner' AS concept),
    STRUCT('oslo grünerløkka' AS pattern, 'Oslo Grünerløkka' AS concept),
    -- Bare 'grünerløkka' for ad-sets like "Oslo city - Grünerløkka - Doelgroep breed".
    STRUCT('grünerløkka' AS pattern, 'Oslo Grünerløkka' AS concept),
    STRUCT('seaside-1' AS pattern, 'Seaside 1' AS concept),
    STRUCT('seaside-2' AS pattern, 'Seaside 2' AS concept),
    STRUCT('seaside-3' AS pattern, 'Seaside 3' AS concept),
    STRUCT('seaside-4' AS pattern, 'Seaside 4' AS concept),
    STRUCT('bergen aan zee' AS pattern, 'Bergen aan Zee' AS concept),
    STRUCT('breda' AS pattern, 'Breda' AS concept),
    STRUCT('inland-1' AS pattern, 'Inland 1' AS concept),
    -- Waterfront synonyms (Meta names were not renamed).
    STRUCT('stockholm waterfront' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('stockholm marine' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('waterfront' AS pattern, 'Stockholm Waterfront' AS concept),
    STRUCT('marine' AS pattern, 'Stockholm Waterfront' AS concept),
    -- Östermalm / Södermalm (case-insensitive; Scandinavian ø supported).
    STRUCT('östermalm' AS pattern, 'Östermalm' AS concept),
    STRUCT('södermalm' AS pattern, 'Södermalm' AS concept),
    -- Cluster patterns (mostly ad-set level inside funnel campaigns).
    STRUCT('stockholm city' AS pattern, 'Stockholm City' AS concept),
    STRUCT('helsinki city' AS pattern, 'Helsinki City' AS concept),
    STRUCT('oslo city' AS pattern, 'Oslo City' AS concept),
    STRUCT('helsinki' AS pattern, 'Helsinki' AS concept),
    -- 'oasis' is the Northern Sauna-internal name for Northern Sauna Kallio. Whole-word,
    -- padded with spaces; the haystack is wrapped to make this safe at
    -- string boundaries.
    STRUCT(' oasis ' AS pattern, 'Helsinki Kallio' AS concept)
  ])
),

-- ============================================================
-- Concept → booking-location expansion (shared between Google
-- and Meta). Single-location concepts have one row at 1.0;
-- multi-location concepts (Waterfront + four city/helsinki
-- clusters) have multiple rows whose sub_weights sum to 1.0.
-- ============================================================
location_expansion AS (
  SELECT concept, location, sub_weight FROM UNNEST([
    -- Single-location concepts.
    STRUCT('Stockholm Waterfront' AS concept, "Northern Sauna Stockholm Waterfront" AS location, 1.0 AS sub_weight),
    STRUCT('Stockholm North' AS concept, 'Northern Sauna Stockholm' AS location, 1.0 AS sub_weight),
    STRUCT('Stockholm Waterside' AS concept, 'Northern Sauna Waterside' AS location, 1.0 AS sub_weight),
    STRUCT('Helsinki Kallio' AS concept, 'Northern Sauna Kallio' AS location, 1.0 AS sub_weight),
    STRUCT('Helsinki Kamppi' AS concept, 'Northern Sauna Kamppi' AS location, 1.0 AS sub_weight),
    STRUCT('Oslo Frogner' AS concept, 'Northern Sauna Frogner' AS location, 1.0 AS sub_weight),
    STRUCT('Oslo Grünerløkka' AS concept, 'Northern Sauna Grünerløkka' AS location, 1.0 AS sub_weight),
    STRUCT('Seaside 1' AS concept, 'Northern Sauna Seaside 1' AS location, 1.0 AS sub_weight),
    STRUCT('Seaside 2' AS concept, 'Northern Sauna Seaside 2' AS location, 1.0 AS sub_weight),
    STRUCT('Seaside 3' AS concept, 'Northern Sauna Seaside 3' AS location, 1.0 AS sub_weight),
    STRUCT('Seaside 4' AS concept, 'Northern Sauna Seaside 4' AS location, 1.0 AS sub_weight),
    STRUCT('Bergen aan Zee' AS concept, 'Northern Sauna Bergen aan Zee' AS location, 1.0 AS sub_weight),
    STRUCT('Breda' AS concept, 'Northern Sauna Breda' AS location, 1.0 AS sub_weight),
    STRUCT('Inland 1' AS concept, 'Northern Sauna Inland 1' AS location, 1.0 AS sub_weight),
    STRUCT('Östermalm' AS concept, 'Northern Sauna Östermalm' AS location, 1.0 AS sub_weight),
    STRUCT('Södermalm' AS concept, 'Northern Sauna Södermalm' AS location, 1.0 AS sub_weight),

    -- Shared Waterfront.
    STRUCT('Stockholm Waterfront' AS concept, 'Northern Sauna Södermalm' AS location, 0.5 AS sub_weight),
    STRUCT('Stockholm Waterfront' AS concept, 'Northern Sauna Östermalm' AS location, 0.5 AS sub_weight),

    -- Cluster: Stockholm City. Waterfront 50/50 baked in directly.
    STRUCT('Stockholm City' AS concept, 'Northern Sauna Södermalm' AS location, 0.1 AS sub_weight),
    STRUCT('Stockholm City' AS concept, 'Northern Sauna Östermalm' AS location, 0.1 AS sub_weight),
    -- Stockholm Waterfront carries 0.4 of the Stockholm City cluster because the
    -- Pier sauna books under the same Bookeo venue.
    STRUCT('Stockholm City' AS concept, "Northern Sauna Stockholm Waterfront" AS location, 0.4 AS sub_weight),
    STRUCT('Stockholm City' AS concept, 'Northern Sauna Stockholm' AS location, 0.2 AS sub_weight),
    STRUCT('Stockholm City' AS concept, 'Northern Sauna Waterside' AS location, 0.2 AS sub_weight),
    STRUCT('Helsinki City' AS concept, 'Northern Sauna Kallio' AS location, 0.5 AS sub_weight),
    STRUCT('Helsinki City' AS concept, 'Northern Sauna Kamppi' AS location, 0.5 AS sub_weight),
    STRUCT('Oslo City' AS concept, 'Northern Sauna Frogner' AS location, 0.5 AS sub_weight),
    STRUCT('Oslo City' AS concept, 'Northern Sauna Grünerløkka' AS location, 0.5 AS sub_weight),
    STRUCT('Helsinki' AS concept, 'Northern Sauna Seaside 3' AS location, 0.20 AS sub_weight),
    STRUCT('Helsinki' AS concept, 'Northern Sauna Seaside 1' AS location, 0.20 AS sub_weight),
    STRUCT('Helsinki' AS concept, 'Northern Sauna Seaside 2' AS location, 0.20 AS sub_weight),
    STRUCT('Helsinki' AS concept, 'Northern Sauna Seaside 4' AS location, 0.20 AS sub_weight),
    STRUCT('Helsinki' AS concept, 'Northern Sauna Bergen aan Zee' AS location, 0.20 AS sub_weight)
  ])
),

-- ============================================================
-- Cluster override rule: when `child` is matched on the same
-- campaign/ad-set, drop `cluster`. Same shape as the legacy
-- Östermalm/Södermalm → drop Stockholm Waterfront rule, generalised.
-- ============================================================
cluster_overrides AS (
  SELECT cluster, child FROM UNNEST([
    STRUCT('Stockholm City' AS cluster, 'Östermalm' AS child),
    STRUCT('Stockholm City' AS cluster, 'Södermalm' AS child),
    STRUCT('Stockholm City' AS cluster, 'Stockholm Waterfront' AS child),
    STRUCT('Stockholm City' AS cluster, 'Stockholm North' AS child),
    STRUCT('Stockholm City' AS cluster, 'Stockholm Waterside' AS child),
    STRUCT('Stockholm Waterfront' AS cluster, 'Östermalm' AS child),
    STRUCT('Stockholm Waterfront' AS cluster, 'Södermalm' AS child),
    STRUCT('Helsinki City' AS cluster, 'Helsinki Kallio' AS child),
    STRUCT('Helsinki City' AS cluster, 'Helsinki Kamppi' AS child),
    STRUCT('Oslo City' AS cluster, 'Oslo Frogner' AS child),
    STRUCT('Oslo City' AS cluster, 'Oslo Grünerløkka' AS child),
    STRUCT('Helsinki' AS cluster, 'Seaside 3' AS child),
    STRUCT('Helsinki' AS cluster, 'Seaside 1' AS child),
    STRUCT('Helsinki' AS cluster, 'Seaside 2' AS child),
    STRUCT('Helsinki' AS cluster, 'Seaside 4' AS child),
    STRUCT('Helsinki' AS cluster, 'Bergen aan Zee' AS child)
  ])
),

-- ============================================================
-- Bookings aggregated by date and location.
-- Bookings semantics: prefer `bookings_excl_canceled` (canonical
-- default, matches dashboards) or `bookings_total` (all statuses).
-- The bare `bookings` column is preserved as a legacy alias of
-- `bookings_total` for backwards compat with ad-hoc consumers.
-- ============================================================
bookings AS (
  SELECT
    DATE(visit_datetime) AS date,
    location,
    COUNT(*) AS bookings,
    COUNT(*) AS bookings_total,
    COUNTIF(status != 'canceled') AS bookings_excl_canceled,
    SUM(participants) AS participants,
    SUM(net_amount) AS revenue,
    -- `revenue` includes canceled bookings whose `net_amount` was preserved
    -- by the API (~5% of revenue in the 2025-05–2026-05 window). Use
    -- `revenue_excl_canceled` for ROI-style ratios where the booking-count
    -- side already excludes canceled (the dashboard convention).
    SUM(IF(status != 'canceled', net_amount, 0)) AS revenue_excl_canceled
  FROM `demo-project.demo_data.bookings`
  WHERE visit_datetime IS NOT NULL
  GROUP BY date, location
),

-- ============================================================
-- Google Ads concept allocation
-- ============================================================
google_concepts_raw AS (
  SELECT DISTINCT
    c.campaign_id,
    cm.concept
  FROM `demo-project.google_ads.ads_Campaign_2079223948` c
  CROSS JOIN google_concept_map cm
  WHERE c._DATA_DATE = c._LATEST_DATE
    AND STRPOS(LOWER(c.campaign_name), cm.pattern) > 0
),

-- LEFT JOIN anti-join form (BigQuery cannot de-correlate the
-- equivalent NOT EXISTS at plan time when the source row count is
-- modest, even though it passes dry-run parsing).
google_concepts_resolved AS (
  SELECT r.campaign_id, r.concept
  FROM google_concepts_raw r
  LEFT JOIN cluster_overrides o ON o.cluster = r.concept
  LEFT JOIN google_concepts_raw r2
    ON r2.campaign_id = r.campaign_id
    AND r2.concept = o.child
  GROUP BY r.campaign_id, r.concept
  HAVING SUM(IF(r2.concept IS NOT NULL, 1, 0)) = 0
),

google_concept_weights AS (
  SELECT
    campaign_id,
    concept,
    1.0 / COUNT(*) OVER (PARTITION BY campaign_id) AS concept_weight
  FROM google_concepts_resolved
),

google_ads_allocation AS (
  SELECT
    cw.campaign_id,
    le.location,
    SUM(cw.concept_weight * le.sub_weight) AS final_weight
  FROM google_concept_weights cw
  JOIN location_expansion le ON cw.concept = le.concept
  GROUP BY cw.campaign_id, le.location
),

google_ads AS (
  SELECT
    s.segments_date AS date,
    a.location,
    SUM(s.metrics_clicks * a.final_weight) AS google_ads_clicks,
    SUM(s.metrics_impressions * a.final_weight) AS google_ads_impressions,
    SUM(s.metrics_cost_micros * a.final_weight) / 1e6 AS google_ads_spend,
    SUM(s.metrics_conversions * a.final_weight) AS google_ads_conversions,
    SUM(s.metrics_conversions_value * a.final_weight) AS google_ads_conversion_value
  FROM `demo-project.google_ads.ads_CampaignBasicStats_2079223948` s
  JOIN google_ads_allocation a ON s.campaign_id = a.campaign_id
  GROUP BY s.segments_date, a.location
),

-- ============================================================
-- Meta Ads concept allocation (campaign-first, ad-set fallback)
-- Reads adset_name + campaign_name directly from ads_insights to
-- preserve the "Meta is name-frozen" architectural premise (no
-- dimension-table join). Resolution rule:
--   1. If campaign_name carries any "specific" concept (anything
--      other than the four cluster concepts Stockholm City /
--      Helsinki City / Oslo City / Helsinki), use the campaign
--      concepts only — ignore ad-set concepts. Prevents stale or
--      copy-pasted ad-set names inside an explicit single-location
--      campaign (e.g. `Clicks | Helsinki Kamppi` with an ad-set
--      named "Campagne Openingsactie 2025 - Helsinki Kallio")
--      from creating false multi-concept splits.
--   2. Otherwise (campaign_name is generic / unmapped, e.g.
--      `Think | Clicks | ABO`, `Do | Conversions | ABO`,
--      `Clicks | Alle locaties`), fall back to ad-set-level
--      detection so funnel city/helsinki cluster targeting still
--      works.
-- Each name is matched in isolation (haystack wrapped with
-- leading/trailing spaces) so word-bounded patterns like
-- ' oasis ' fire cleanly.
-- ============================================================
meta_campaign_concepts AS (
  SELECT DISTINCT
    i.adset_id,
    cm.concept
  FROM (
    SELECT DISTINCT adset_id, campaign_name
    FROM `demo-project.meta_ads.ads_insights`
    WHERE adset_id IS NOT NULL AND campaign_name IS NOT NULL
  ) i
  CROSS JOIN meta_concept_map cm
  WHERE STRPOS(' ' || LOWER(i.campaign_name) || ' ', cm.pattern) > 0
),

meta_adset_concepts AS (
  SELECT DISTINCT
    i.adset_id,
    cm.concept
  FROM (
    SELECT DISTINCT adset_id, adset_name
    FROM `demo-project.meta_ads.ads_insights`
    WHERE adset_id IS NOT NULL AND adset_name IS NOT NULL
  ) i
  CROSS JOIN meta_concept_map cm
  WHERE STRPOS(' ' || LOWER(i.adset_name) || ' ', cm.pattern) > 0
),

-- Adset_ids whose campaign_name yields at least one non-cluster
-- ("specific") concept. Waterfront counts as specific — it is
-- the campaign's full intent, not a generic catch-all.
meta_campaign_specific AS (
  SELECT DISTINCT adset_id
  FROM meta_campaign_concepts
  WHERE concept NOT IN ('Stockholm City', 'Helsinki City', 'Oslo City', 'Helsinki')
),

meta_concepts_raw AS (
  -- Campaign concepts win (full set, including any cluster) when
  -- the campaign name carries a specific concept.
  SELECT c.adset_id, c.concept
  FROM meta_campaign_concepts c
  WHERE c.adset_id IN (SELECT adset_id FROM meta_campaign_specific)
  UNION DISTINCT
  -- Otherwise, fall back to ad-set concepts.
  SELECT a.adset_id, a.concept
  FROM meta_adset_concepts a
  WHERE a.adset_id NOT IN (SELECT adset_id FROM meta_campaign_specific)
),

meta_concepts_resolved AS (
  SELECT r.adset_id, r.concept
  FROM meta_concepts_raw r
  LEFT JOIN cluster_overrides o ON o.cluster = r.concept
  LEFT JOIN meta_concepts_raw r2
    ON r2.adset_id = r.adset_id
    AND r2.concept = o.child
  GROUP BY r.adset_id, r.concept
  HAVING SUM(IF(r2.concept IS NOT NULL, 1, 0)) = 0
),

meta_concept_weights AS (
  SELECT
    adset_id,
    concept,
    1.0 / COUNT(*) OVER (PARTITION BY adset_id) AS concept_weight
  FROM meta_concepts_resolved
),

meta_ads_allocation AS (
  SELECT
    cw.adset_id,
    le.location,
    SUM(cw.concept_weight * le.sub_weight) AS final_weight
  FROM meta_concept_weights cw
  JOIN location_expansion le ON cw.concept = le.concept
  GROUP BY cw.adset_id, le.location
),

-- Meta purchase conversions/values are extracted from the JSON
-- actions/action_values arrays — same pattern as v_campaign_performance.sql:32-50.
-- Filtering both UNNESTs to action_type='purchase' yields at most one row per
-- ads_insights row, so it does not multiply clicks/impressions/spend.
meta_ads AS (
  SELECT
    m.date_start AS date,
    a.location,
    SUM(m.clicks * a.final_weight) AS meta_ads_clicks,
    SUM(m.impressions * a.final_weight) AS meta_ads_impressions,
    SUM(CAST(m.spend AS FLOAT64) * a.final_weight) AS meta_ads_spend,
    SUM(SAFE_CAST(JSON_VALUE(a_conv, '$.value') AS FLOAT64) * a.final_weight) AS meta_ads_conversions,
    SUM(SAFE_CAST(JSON_VALUE(a_val, '$.value') AS FLOAT64) * a.final_weight) AS meta_ads_conversion_value
  FROM `demo-project.meta_ads.ads_insights` m
  JOIN meta_ads_allocation a ON m.adset_id = a.adset_id
  LEFT JOIN UNNEST(JSON_QUERY_ARRAY(m.actions)) AS a_conv
    ON JSON_VALUE(a_conv, '$.action_type') = 'purchase'
  LEFT JOIN UNNEST(JSON_QUERY_ARRAY(m.action_values)) AS a_val
    ON JSON_VALUE(a_val, '$.action_type') = 'purchase'
  GROUP BY m.date_start, a.location
),

-- All date-location combinations from any source.
all_keys AS (
  SELECT date, location FROM bookings
  UNION DISTINCT
  SELECT date, location FROM google_ads
  UNION DISTINCT
  SELECT date, location FROM meta_ads
)

SELECT
  k.date,
  k.location,
  IFNULL(b.bookings, 0) AS bookings,
  IFNULL(b.bookings_total, 0) AS bookings_total,
  IFNULL(b.bookings_excl_canceled, 0) AS bookings_excl_canceled,
  IFNULL(b.participants, 0) AS participants,
  IFNULL(b.revenue, 0) AS revenue,
  IFNULL(b.revenue_excl_canceled, 0) AS revenue_excl_canceled,
  IFNULL(g.google_ads_clicks, 0) AS google_ads_clicks,
  IFNULL(g.google_ads_impressions, 0) AS google_ads_impressions,
  IFNULL(g.google_ads_spend, 0) AS google_ads_spend,
  IFNULL(g.google_ads_conversions, 0) AS google_ads_conversions,
  IFNULL(g.google_ads_conversion_value, 0) AS google_ads_conversion_value,
  IFNULL(m.meta_ads_clicks, 0) AS meta_ads_clicks,
  IFNULL(m.meta_ads_impressions, 0) AS meta_ads_impressions,
  IFNULL(m.meta_ads_spend, 0) AS meta_ads_spend,
  IFNULL(m.meta_ads_conversions, 0) AS meta_ads_conversions,
  IFNULL(m.meta_ads_conversion_value, 0) AS meta_ads_conversion_value
FROM all_keys k
LEFT JOIN bookings b ON k.date = b.date AND k.location = b.location
LEFT JOIN google_ads g ON k.date = g.date AND k.location = g.location
LEFT JOIN meta_ads m ON k.date = m.date AND k.location = m.location
