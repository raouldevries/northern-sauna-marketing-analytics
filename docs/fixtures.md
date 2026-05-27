# Fixture Schemas

This document is the contract between `scripts/generate_demo_data.py` (Phase 3) and the loader bodies that get swapped to read fixtures in Phase 4. Each section below describes one CSV that must exist under `demo_data/` and the exact shape the corresponding `load_*_from_bq` function expects.

The fixtures are **obviously stylized synthetic data**, not Northern Sauna-calibrated values. The goal is for a visitor to instantly recognize the data is synthetic while still seeing meaningful chart structure. Specific calibration choices appear in the "Stylized constants" section at the end of this document.

## Conventions

- **Date range:** every fixture covers the most recent 12 calendar months ending yesterday. The generator computes the range at run time so the demo never goes "stale" on Streamlit Cloud.
- **Determinism:** `Faker(seed=42)` + `numpy.random.default_rng(42)`. Re-running the generator produces byte-identical CSVs.
- **Encoding:** UTF-8, comma-delimited, header row, RFC 4180 quoting. pandas defaults are fine.
- **Locations:** the three internal account IDs (`stockholm`, `helsinki`, `oslo`) are opaque strings; visible display names ("Northern Sauna Stockholm" etc.) come from the `_BQ_TO_STREAMLIT_LOCATION` / `_BQ_TO_STREAMLIT_ACCOUNT` maps in `streamlit/data/bq_client.py`.
- **Currency:** EUR everywhere. Spend values are pre-converted (not micros).

## Fixtures

### bookings.csv

- **Loader:** `_query_bookings` in `streamlit/data/queries.py`
- **Backing view:** `v_bookings_member_enriched`
- **Loader signature:** `(start_date: str, end_date: str, include_canceled=True, date_column="visit_datetime") -> pd.DataFrame`
- **Row volume:** ~3000–8000 over 12 months
- **Columns** (28 total):

| name | dtype | notes |
| --- | --- | --- |
| id | object | composite key `bookeo_{account}_{number}` |
| source_account | object | `stockholm` / `helsinki` / `oslo` |
| customer_email | object | synthetic `customer_{hash}@example.com` |
| customer_name | object | Faker locale `nl_NL` first + last |
| customer_phone | object | Faker NL mobile format |
| location | object | raw BQ location string (later mapped via `_BQ_TO_STREAMLIT_LOCATION`) |
| product_name | object | one of a small fixed catalog (e.g. "Sauna 90 min", "Sauna 120 min") |
| booking_created_at | datetime64 | uniform random 0–60 days before `visit_datetime` |
| visit_datetime | datetime64 | primary filter column |
| status | object | one of `confirmed`, `completed`, `canceled`, `no_show` |
| participants | int64 | 1–6 |
| gross_amount | float64 | `participants * 99.0` (stylized flat unit price) |
| net_amount | float64 | `gross_amount / 1.21` (21% VAT removed) |
| paid_amount | float64 | equals `net_amount` for non-canceled; 0 for canceled |
| end_time | object | ISO string, `visit_datetime + product duration` |
| promotion_name | object | NULL for ~80%; otherwise picks from `{"Spring offer", "Member discount"}` |
| booking_source | object | NULL for ~70%; otherwise `{"website", "google", "referral"}` |
| private_event | object | "false" everywhere |
| is_canceled | object | "true" iff status == canceled |
| cancelation_time | object | ISO string for ~5%; NULL otherwise |
| cancelation_agent | object | NULL or `"customer"` |
| creation_agent | object | "system" |
| last_change_time | object | ISO string == booking_created_at unless canceled |
| last_change_agent | object | matches cancelation_agent when canceled |
| is_no_show | object | "true" iff status == no_show (~2%) |
| coupon_codes_json | object | `"[]"` everywhere |
| is_member | bool | 50/50 split (stylized) |
| membership_end | datetime64 | NULL if not member; otherwise random within next 12 months |

### campaign_performance.csv

- **Loader:** `load_marketing_data_from_bq`
- **Backing view:** `v_campaign_performance`
- **Row volume:** 7 campaigns × ~366 days ≈ 2,562 rows
- **Columns** (11 total): `date, platform, campaign_name, impressions, clicks, spend, ctr, cpc, conversions, conversion_value, reach`
- **Stylized values:** 3 Google + 4 Meta campaigns; €100/day flat spend per campaign, CTR=2%, CPC=€1, CVR=2% (tuned down from 5% so total conversions stay strictly below total non-canceled bookings per plan "no impossible attribution"); `reach` populated only for Meta rows.

### location_performance.csv

- **Loader:** `load_location_performance_from_bq`
- **Backing view:** `v_location_performance`
- **Row volume:** ~365 × 3 ≈ 1,100 rows (one per location-day)
- **Columns** (18 total): `date, location, bookings, bookings_total, bookings_excl_canceled, participants, revenue, revenue_excl_canceled, google_ads_clicks, google_ads_impressions, google_ads_spend, google_ads_conversions, google_ads_conversion_value, meta_ads_clicks, meta_ads_impressions, meta_ads_spend, meta_ads_conversions, meta_ads_conversion_value`. `bookings` is a legacy alias for `bookings_total`.
- **Stylized values:** baseline 5 / 5 / 6 daily bookings (stockholm / helsinki / oslo), +20% weekend lift, Poisson-noised around the baseline. Aggregated from the bookings.csv generator. Ad metrics allocated to locations in equal thirds.

### location_performance_do.csv

- **Loader:** `load_location_performance_do_from_bq`
- **Backing view:** `v_location_performance_do`
- **Columns:** identical to `location_performance.csv` (18 cols)
- **Row volume:** ~75% of `location_performance.csv` (DO-stage subset)
- **Stylized values:** half the spend and 1.4× the CVR of the full table; same shape so the loader can use the same `_load_fixture` helper.

### age_demographics.csv

- **Loader:** `load_age_demographics_from_bq` (custom UNION; no backing view)
- **Row volume:** ~12–14 rows total (not date-partitioned in the loader output)
- **Columns** (7 total): `platform, age_group, impressions, clicks, spend, conversions, ctr`. Note: `conversions` is 0 for Meta rows (the source table has no conversion data).
- **Stylized values:** uniform distribution across age buckets `18-24, 25-34, 35-44, 45-54, 55-64, 65+`; `25-34` and `35-44` get a 1.5× weight to mimic a plausible audience skew without leaking real numbers.

### gender_demographics.csv

- **Loader:** `load_gender_demographics_from_bq` (custom UNION)
- **Row volume:** 4 rows (2 platforms × 2 genders; `UNDETERMINED` excluded by loader)
- **Columns** (9 total): `platform, gender, impressions, clicks, spend, conversions, conversion_value, cpc, ctr`
- **Stylized values:** 60/40 female/male split per platform.

### device_demographics.csv

- **Loader:** `load_device_demographics_from_bq` (custom UNION)
- **Row volume:** 8 rows (2 platforms × 4 devices)
- **Columns** (7 total): `platform, device, impressions, clicks, spend, conversions, conversion_value`
- **Stylized values:** Mobile 70%, Desktop 20%, Tablet 8%, Other 2%.

### platform_placement.csv

- **Loader:** `load_platform_placement_from_bq` (direct Meta query; no view)
- **Row volume:** 15 rows (3 publishers × 5 positions, even spend split)
- **Columns** (8 total): `publisher_platform, platform_position, impressions, clicks, spend, reach, cpc, ctr`
- **Stylized values:** 3 publisher platforms × 5 positions; even spend split.

### google_ads_network.csv

- **Loader:** `load_google_ads_network_from_bq`
- **Row volume:** 2 rows (Search, Display)
- **Columns** (9 total): `network, impressions, clicks, spend, conversions, conversion_value, cpc, ctr, cpa`
- **Stylized values:** Search 70%, Display 30% of spend.

### google_ads_campaign_network.csv

- **Loader:** `load_google_ads_campaign_network_from_bq`
- **Row volume:** ~20–60 rows (campaign × network combinations with spend > €1)
- **Columns** (8 total): `campaign_name, network, impressions, clicks, spend, conversions, ctr, cpa`

### google_ads_search_position.csv

- **Loader:** `load_google_ads_search_position_from_bq`
- **Row volume:** 4 rows (slots 1, 2, 3, "Other")
- **Columns** (8 total): `slot, impressions, clicks, spend, conversions, ctr, cpa`

### daily_marketing_summary.csv

- **Loader:** `load_daily_marketing_summary_from_bq`
- **Backing view:** `v_daily_marketing_summary`
- **Row volume:** 365 × 4 = 1,460 rows (one per source per date)
- **Columns** (7 total): `date, source, impressions, clicks, spend, sessions, conversions`. Sources: `google_ads`, `meta_ads`, `ga4`, `search_console`. NULLs where a metric doesn't apply (e.g. `sessions` is NULL for ad rows).
- **Generation:** derived from the other fixtures so it stays internally consistent.

### ga4_traffic.csv

- **Loader:** `load_ga4_traffic_from_bq`
- **Row volume:** ~365 × 5 = ~1,800 rows (one per source/medium combination per day)
- **Columns** (11 total): `date, session_source, session_medium, session_default_channel_group, sessions, total_users, new_users, engaged_sessions, engagement_rate, screen_page_views, average_session_duration`
- **Stylized values:** 5 fake source/medium combos (e.g. `(google, organic)`, `(google, cpc)`, `(direct, none)`, `(facebook, social)`, `(newsletter, email)`); flat 200 sessions/day baseline + 20% weekend lift, 60% engagement rate, 3 page views per session, 90-second average session.

### search_console_queries.csv

- **Loader:** `load_search_console_from_bq`
- **Row volume:** ~365 × 50 = ~18,000 rows
- **Columns** (6 total): `data_date, query, clicks, impressions, avg_position, ctr`
- **Stylized values:** 50 obviously-demo query strings (e.g. `sauna near demo`, `wellness location a`, `relax visit booking`); deterministic per-query impression/click curves; positions in 1.5–10 range.

### search_console_pages.csv

- **Loader:** `load_search_console_pages_from_bq`
- **Row volume:** ~365 × 10 = ~3,600 rows
- **Columns** (5 total): `data_date, url, clicks, impressions, avg_position`
- **Stylized values:** 10 fake URLs (e.g. `/sauna/stockholm`, `/booking`, `/about`, `/contact`); deterministic per-URL traffic curves.

## Stylized constants

User-confirmed calibration decisions for Phase 3 (see plan Step 3.1):

- Flat **€99 unit price** per booking participant. 21% VAT removed for `net_amount`.
- **5 / 5 / 6 baseline bookings/day** across `stockholm / helsinki / oslo` (one location bumped for chart variety). Poisson-noised so daily counts look organic; long-run mean is stylized. Tuned so the 12-month bookings.csv lands in the plan's 3,000–8,000 row target.
- **+20% weekend lift** on bookings, sessions, and ad-spend KPIs. No holiday effects, no seasonality curves.
- **50 / 50 member ratio**.
- **5% cancel rate, 2% no-show rate.**
- **€100/day/campaign** flat ad spend; **2% CTR**, **€1 CPC**, **2% CVR** across the board. CVR tuned down from the plan's 5% to keep total conversions strictly below total non-canceled bookings (plan: "no impossible attribution").
- All "calculated" columns (CPC, CTR, CPA, ctr, avg_position) are computed from the underlying raw integers / floats in the generator — not duplicated as primary inputs. This is what keeps cross-fixture consistency: a Phase 4 smoke check can re-derive ratios and assert internal consistency.

## Dependency note

Phase 4 loaders read these CSVs only when `DEMO_MODE=true`; the live path is preserved. Phase 3 must complete before any Phase 4 smoke test of pages 2, 5, 7, 10, 11. Pages 1 (Overview) and 8/12 (stubbed in Step 5.2) do not depend on these fixtures.

## Phase 4.5 — Widget-call inventory (pre-flight for Step 5.1)

Grep across `streamlit/pages/` for `ask_the_data`, `copy_bot`, `render_page_ai_widget`:

| Page | `ask_the_data` imports | `copy_bot` imports | `render_page_ai_widget(...)` call sites |
|---|---|---|---|
| `1_overview.py` | 0 | 0 | 0 |
| `2_turnover.py` | 1 (line 22) | 0 | 1 (line 696) |
| `3_customers.py` | 1 (line 26) | 0 | 1 (line 1537) |
| `4_members.py` | 1 (line 15) | 0 | 1 (line 1300) |
| `5_capacity.py` | 1 (line 15) | 0 | 1 (line 1029) |
| `6_promotions.py` | 1 (line 15) | 0 | 1 (line 776) |
| `7_marketing.py` | 1 (line 41) | 0 | 1 (line 3453) |
| `8_reviews.py` | 1 (line 24) | 0 | 3 (lines 719, 728, 1294) |
| `10_bookings.py` | 1 (line 22) | 0 | 1 (line 1115) |
| `11_organic_seo.py` | 1 (line 19) | 0 | 1 (line 931) |
| `12_ai_assistant.py` | 11 imports (lines 9-26) | 3 imports (lines 31-33) | 0 — page itself IS the AI page |
| `about_ai_assistant.py` | 0 | 0 | 0 |

**Coverage check:** Step 5.1 strips widget calls from pages 2/3/4/5/6/7/8/10/11. Step 5.2 stubs pages 8 and 12. Pages 1 and `about_ai_assistant.py` have no hits — no edits required. Together the included list (Step 5.1) + the stub list (Step 5.2) covers every grep hit; no files outside the touch list reference the subsystem.
