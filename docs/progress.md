# Demo Repo Progress

Tracking implementation against `plans/public-demo-showcase-northern-sauna-marketing-analytics-plan.md` (lives in the private `northern-sauna-platform` repo).

## Phase 1 — Demo Repo Bootstrap & File Sanitization

- [x] Step 1.1: Initialize the demo repo and copy the code surface
- [x] Step 1.2: Strip sensitive files from the copied surface
- [x] Step 1.3: Scrub hardcoded identifiers (2026-05-26)

### Step 1.3 audit-loop notes

Banned-token grep gate (`scripts/validate_identifiers.sh`) covers `<REAL_GCP_PROJECT>`, `412680851`, `raoul@soulkitchen`, `soulkitchen`, `demo_data` — all 0 hits.

Ship-file changes (preserved behaviour when env vars set to real values):
- `streamlit/data/bq_client.py` — `PROJECT_ID`, `GA4_PROPERTY_ID`, `DATASET` switched to `os.environ.get(..., demo-default)`.
- `streamlit/data/queries.py` — `analytics_412680851*` literals replaced with `analytics_{GA4_PROPERTY_ID}*` inside existing f-strings; added `GA4_PROPERTY_ID` to the import.
- `streamlit/features/revenue/queries.py` — added `BOOKINGS_TABLE` import; converted 5 query strings to f-strings; `<REAL_GCP_PROJECT>.demo_data.bookings` → `{BOOKINGS_TABLE}`.
- `src/utils/bigquery.py` — default `dataset_id` literal scrubbed (Bookeo sync utility, not reachable from streamlit demo).

Dead-walking file changes (slated for Step 5.3 deletion — literal placeholder swap only, no env-driven plumbing):
- `streamlit/ask_the_data/*.py` + `schema_catalog.yaml`, `streamlit/copy_bot/queries.py`.
- `sql/views/*.sql`, `sql/monitoring/*.sql`, `sql/monitoring/README.md` — DDL artefacts, never deployed from the demo repo.

Audit triage:
- Self-audit returned 3 P2 findings; #1 accepted (dead-walking drift, scoped out by plan), #2 fixed (added `demo_data` to gate + scrubbed 67 hits), #3 fixed (created `docs/progress.md`).
- Codex returned 4 P1 + 1 P2; **all 5 dismissed** as out-of-scope. Each finding maps to a planned Phase 2–5 step that addresses the underlying concern (DEMO_MODE gating, subsystem deletion, fixture swap). Findings reflect Codex not having full plan context — they are valid for a *production fork* but not for this public-only demo repo. See commit body for per-finding triage.

## Phase 2 — Demo-Mode Bootstrap

- [x] Step 2.1: DEMO_MODE flag + auth bypass in `app.py` (2026-05-26)
- [x] Step 2.2: BigQuery client gating in `bq_client.py` (2026-05-26)
- [x] Step 2.3: Page-level secret read gated in `pages/1_overview.py` (2026-05-26)
- [x] Step 2.4: `streamlit/.streamlit/secrets.toml.example` added (2026-05-26)

### Phase 2 (2.1+2.2+2.3) audit-loop notes

Ran as a single audit-loop cycle — the three steps form a coherent bypass surface and Codex's dismissed Step 1.3 P1s explicitly hinged on these landing together.

**DEMO_MODE flag** (env-driven, `os.environ.get("DEMO_MODE", "").lower() == "true"`) declared at module load in `streamlit/app.py`, `streamlit/data/bq_client.py`, and `streamlit/pages/1_overview.py`. Read once at import time so `@st.cache_resource` semantics hold across the session.

**Auth bypass in `app.py`**:
- `BQ_AVAILABLE = (not DEMO_MODE) and ("gcp_service_account" in st.secrets)` — short-circuit prevents `st.secrets` access in demo mode.
- `if DEMO_MODE: st.session_state.authenticated = True` right after session-state init, so the unauthenticated login branch (which ends in `st.stop()`) is never entered.
- BQ error block and `APP_PASSWORD` check both wrapped in `if not DEMO_MODE:`.
- `app_password = ""` placeholder in the demo else-branch (never consumed because the auth branch is skipped).

**Client gating in `bq_client.py`**: both `_get_bq_client()` (cached) and the public `get_bq_client()` wrapper early-return `None` in demo mode. Return type widened to `bigquery.Client | None`.

**Feedback gating in `data/feedback.py` (pulled forward from Step 4.4)**: `insert_feedback()` no-ops, `get_feedback()` and `get_all_feedback()` return empty DataFrames in demo mode. This addresses a Codex P1 that would otherwise crash the Overview page on landing — Overview unconditionally calls `get_all_feedback()` (line 389) and would hit `client.query(None)` -> `AttributeError` without the gate.

Audit triage:
- Self-audit: zero findings.
- Codex: 2 P1 findings.
  - **P1 #1 (overview feedback crash)** — fixed by pulling Step 4.4's feedback gating forward into Phase 2.
  - **P1 #2 (Northern Sauna AI log table + Ask-the-Data drawer crash on non-overview pages)** — deferred to Step 5.1 (strips `render_page_ai_widget()` from pages 2-11), Step 5.2 (stubs page 12), Step 5.3 (deletes `ask_the_data/`). Page 12 isn't loaded at app boot (Streamlit lazy-loads pages); the AI drawer only triggers on navigation. Bounded gap window: pages 2-12 are broken in demo mode between this commit and Step 5.1, but the demo is not deployed until Phase 6 and Step 5.1 ships well before then.

Runtime smoke (no streamlit runtime, used `__wrapped__` to bypass caching decorators):
- `DEMO_MODE=true python -c "..."` confirmed: `DEMO_MODE is True`, both client factories return `None`, `get_all_feedback()` returns empty DataFrame with correct columns, `insert_feedback()` no-ops without raising.
- `DEMO_MODE` unset: flag defaults to `False`, ship behavior preserved.

## Phase 3 — Synthetic Data Generation

- [x] Step 3.1: `docs/fixtures.md` — fixture schema reference (2026-05-26)
- [x] Step 3.2: bookings fixture generator (2026-05-26)
- [x] Step 3.3: marketing fixtures (2026-05-26)
- [x] Step 3.4: GA4 + Search Console fixtures (2026-05-26)

### Steps 3.3 + 3.4 audit-loop notes (cycle #4 of session)

Extended `scripts/generate_demo_data.py` by ~700 lines, adding 14 new builders + per-fixture validators + a cross-fixture attribution assertion (campaign conversions ≤ non-canceled bookings). Single run produces all 15 CSVs in `demo_data/`: bookings, campaign_performance, location_performance (+ `_do` variant), age/gender/device demographics, platform_placement, google_ads_network / `_campaign_network` / `_search_position`, ga4_traffic, search_console_queries + `_pages`, daily_marketing_summary. Total 21,556 lines / ~2 MB.

CVR re-tuned from 5% → 2% so 7 campaigns × 100 clicks/day × 2% = 14 conv/day ≈ 5,316/year stays strictly below the 5,842 non-canceled bookings (plan: "no impossible attribution"). Documented in `docs/fixtures.md` with the same note.

Audit triage (self-audit subagent, codex skipped — same budget rationale as cycle #3):
- 4 P1 silent-chart-breakage findings — **all fixed**:
  - `google_ads_search_position` slots `"1"/"2"/"3"/"Other"` → `"SEARCH_TOP"/"SEARCH_OTHER"` (page filters on raw enum).
  - `platform_placement` publisher names `"Facebook"/"Instagram"/"Audience Network"` → lowercase enum (`facebook`/`instagram`/`audience_network`).
  - `google_ads_network` + `GOOGLE_CAMPAIGNS` objective tags `"Search"/"Display"` → `"SEARCH"/"CONTENT"` (page filters on uppercase BQ enum; also affects `_build_google_ads_search_position`'s campaign-set filter and `_build_location_performance`'s DO filter).
  - `age_demographics` schema dropped `ctr` (not in loader) and added `conversion_value` (in loader). Matches `load_age_demographics_from_bq` return shape.
- 2 P2 defensive validator extensions — **both added**:
  - `_validate_campaign_performance` now asserts all three stylized ratios: spend ≈ clicks × CPC, clicks ≈ impressions × CTR, conversions ≈ clicks × CVR.
  - `_validate_daily_marketing_summary` now asserts row count (4 × n_days) and per-source null patterns (ga4 has sessions only; sc has impressions/clicks only).
- 1 P2 brand-safety finding — **accepted out-of-scope**: `stockholm`/`helsinki`/`oslo` appear in `SC_QUERY_TERMS` and `SC_PAGES`. These are the same opaque internal account IDs the plan explicitly preserved in Step 1.3 (`_BQ_TO_STREAMLIT_LOCATION`), so SC reuse is consistent with the plan's brand decision. Renaming is a stylistic preference, not a functional break.

Runtime:
- Re-ran the generator after each fix. All 15 fixture asserts pass.
- Final sha-of-CSV-shas: `38ec287e0274fe6cf0cf8dcc80acfc9a9a74e40a9d772679d4445a0cdfaba4cf` — stable across two consecutive runs.
- `bash scripts/validate_identifiers.sh` exit 0.
- `ruff check scripts/generate_demo_data.py` clean.

### Step 3.2 audit-loop notes (cycle #3 of session)

`scripts/generate_demo_data.py` — Faker(seed=42) + numpy.random.default_rng(42), Poisson-noised daily-booking draws around a 5/5/6 baseline with +20% weekend lift. Produces `demo_data/bookings.csv` (6,135 rows, 28 columns, 366-day window). Two consecutive runs produce byte-identical CSVs (sha256 stable). Inline assertions in `_validate_bookings()` lock the column tuple, row-count bounds, gross = participants × €99, and the ±5% member-ratio envelope.

`pyproject.toml`: added `faker>=22.0` to `[project.optional-dependencies] dev` (runtime path stays Faker-free; Streamlit Cloud install doesn't need it).

`docs/fixtures.md`: revised the documented daily rates from the plan's hypothetical "100/100/120" to the actual "5/5/6 + Poisson + weekend lift". The original "100/100/120" example was inconsistent with the 3,000–8,000 row target acceptance criterion — 100/day×3×365 = 109k.

`streamlit/data/queries.py` (single defensive line): `bq_df["private_event"].astype(str).fillna(...).str.lower() == "true"`. The transform receives bool dtype from `pd.read_csv` of the demo CSV (pandas auto-infers all-"false" columns to bool), and the `.str` accessor would crash. `.astype(str)` is a no-op on the BQ path (already object dtype) and converts the demo path correctly. This was a P1 finding from the self-audit — see commit for the full trace.

Audit triage:
- Self-audit: 1 P1 — fixed (the private_event dtype crash above). 0 P2.
- **Codex audit skipped this cycle** by deliberate budget choice — cycle #3 of the session hits the CLAUDE.md context-guard threshold and the next move is `/handover`. The blast radius of a deterministic CSV generator is small (no security-sensitive surface, no shared state, output is testable byte-for-byte), and the self-audit subagent caught the one real bug. Codex re-engages naturally in the next session's cycle.

Runtime smoke:
- `python scripts/generate_demo_data.py --out demo_data/` → 6,135 rows.
- SHA-256 stable across two runs.
- `pd.read_csv(...)` + `_transform_bq_to_bookeo_format(...)` → 6,135 transformed rows / 5,842 non-canceled, `df1["Private event"]` dtype `bool`, all False.

## Phase 4 — Backend Swap

- [x] Step 4.1 — `_query_bookings` reads `demo_data/bookings.csv` under DEMO_MODE; `_transform_bq_to_bookeo_format` runs unchanged on the fixture (6,135 → 5,842 non-canceled).
- [x] Step 4.2 — 10 marketing loaders gated by DEMO_MODE early-return through `_load_fixture`.
- [x] Step 4.3 — `load_ga4_traffic_from_bq`, `load_search_console_from_bq`, `load_search_console_pages_from_bq` read fixtures.
- [x] Step 4.4 — `_demo_freshness` + `_demo_coverage` derive from fixture date ranges; `insert_feedback` was already no-op in Phase 2.
- [x] Step 4.5 — Widget-call inventory committed to `docs/fixtures.md` (9 pages strip + page 12 stub + 2 widget-free covers all hits).

### Step 4 audit-loop notes (cycle #5 of multi-session run)

`streamlit/data/queries.py` +208 lines. One shared `_load_fixture(name, start_date, end_date, date_column)` helper does CSV read + Timestamp coercion + inclusive date filter. Coercion is the load-bearing detail: BQ's `to_dataframe()` returns DATE columns as db-dtypes Timestamps with `.strftime` / `.dt`, but `pd.read_csv` returns object strings — without coercion, page 11's `sc_df["data_date"].min().strftime("%-d %b %Y")` crashes.

Audit triage:
- Self-audit: 1 P0 — fixed (the `data_date.strftime` crash above; coercion moved into `_load_fixture` so every caller benefits). 1 P2 — accepted out-of-scope (location label remap on `load_location_performance_*` — demo labels aren't in `_BQ_TO_STREAMLIT_LOCATION` by design).
- Codex (re-engaged after cycle #4 skip): 1 P1 + 1 P2, both **DOCUMENT**:

| # | Finding | Severity | Classification |
|---|---------|----------|----------------|
| 1 | Demographic / network / placement / search-position / campaign-network loaders return full-window aggregates regardless of requested date range in demo mode. ~37% spend overstatement when user narrows range. | P1 | DOCUMENT — Phase 3 emitted these as pre-computed aggregates with no date dimension; fix requires regenerating fixtures with a date column. Out of Phase 4 scope. Inline comment in `queries.py` warns future readers. |
| 2 | `1_overview.py:258` gates `get_data_freshness/coverage` behind `BQ_AVAILABLE`, leaving the source-status table blank in demo mode despite the new stubs. | P2 | DOCUMENT — Phase 5 UI polish concern (parallels the deferred `render_page_ai_widget` cleanup). |

Runtime smoke (via main-repo venv):
- `_query_bookings('2025-05-25','2025-05-26')` → 31 rows, transform → 6,135 / 5,842 split.
- `load_search_console_from_bq('2025-06-01','2025-06-30')` → 300 rows, `data_date` dtype `datetime64[ns]`, `.strftime` works.
- `load_ga4_traffic_from_bq`, `load_location_performance_from_bq` → date columns coerced.
- `_demo_freshness()` → `bookings_created=2026-05-24`, `ga4=2026-05-25`, etc. — derived from fixtures, evergreen.
- `_demo_coverage()` → 5 source rows (Bookeo, Google Ads, Meta Ads, GA4, Search Console).
- `bash scripts/validate_identifiers.sh` exit 0.

## Phase 5 — UI Polish & Stubs

- [x] Step 5.1 — Removed `render_page_ai_widget(...)` imports + call sites from 8 pages (2/3/4/5/6/7/10/11). Pages 1 + about_ai_assistant never had the widget.
- [x] Step 5.2 — Pages 8 (Reviews) and 12 (Northern Sauna AI) replaced with text-only "Live build only" stubs sharing `streamlit/components/live_build_stub.py`. 8_reviews.py 1,303 → 71 LOC, 12_ai_assistant.py 1,021 → 73 LOC.
- [x] Step 5.3 — `streamlit/ask_the_data/` (15 files) and `streamlit/copy_bot/` (9 files) removed. `load_gmb_reviews_from_bq` + `load_ad_copy_coverage_from_bq` removed from `data/queries.py` and from the `bq_data_loader.py` shim. 3 GMB SQL files deleted. Stale GMB freshness block dropped from `sql/monitoring/data_freshness_check.sql`. Dangling `gmb_reviews_df` / `gmb_reviews_last_refresh` session-state keys removed.
- [x] Step 5.4 — Portfolio `README.md` written: project intro, live-demo placeholder, page index, stack, architecture diagram (sources → sync → storage → frontend), local-run instructions, deterministic-fixtures note, agentic-workflow callout (`/plan-loop`, `/audit-loop`, `/handover`, identifier gate), explicit "what's not in the demo" list.
- [x] Step 5.5 — Banner + footer mounted on all 12 pages via new reusable `streamlit/components/demo_banner.py` (`render_demo_banner()` + `render_footer()`). Both short-circuit when `DEMO_MODE` is not set so live builds get neither. Mount uses a Python helper that inserted the import + `render_demo_banner()` after each page's `render_sidebar_nav(...)` call and appended `render_footer()` at EOF; 8/12 stubs and `app.py` handled separately. Per-card `(demo data)` subscript on 50 `st.metric` calls deliberately skipped after user confirmation — the persistent banner ("every number here is generated from scripts/generate_demo_data.py") is the disclaimer, per-card repetition is visual noise.

### Step 5.1–5.3 audit-loop notes (cycle #6 of multi-session run)

Single bundled commit `e741292`: 43 files changed, +161 / −12,718. The cleanup is mechanical because the 8 included pages each had a single bottom-of-file `render_page_ai_widget("...")` call (no enclosing container — verified with ±2-line grep), and the two stubbed pages just call into the new reusable component.

Audit triage:
- Self-audit: 1 P2 — fixed (stale `gmb_reviews` block in `sql/monitoring/data_freshness_check.sql`). Same pass surfaced orphan `gmb_reviews_df` / `gmb_reviews_last_refresh` session-state keys; removed.
- Codex: **No P0/P1/P2 findings.**

Gate proofs (all from inside the demo repo):
- `grep -rnE "ask_the_data|copy_bot|render_page_ai_widget" streamlit/pages/ sql/` → exit 1.
- `grep -rnE "load_gmb_reviews_from_bq|load_ad_copy_coverage_from_bq" streamlit/ sql/ scripts/` → exit 1.
- `grep -rnE 'st\.secrets\[.?.anthropic.?.\]' streamlit/` → exit 1.
- `bash scripts/validate_identifiers.sh` → exit 0.
- AST parse OK for `pages/8_reviews.py`, `pages/12_ai_assistant.py`, `components/live_build_stub.py`, `data/queries.py`, `data/session.py`, `bq_data_loader.py`.

Design notes:
- `live_build_stub.py` takes (`title`, `description_paragraphs: list[str]`, `why_not_live: str`). One badge + headline + paragraphs + footer block. Text-only — no screenshots (decision: cleaner, zero redaction risk).
- Both stub pages preserve the auth-gate / `set_page_config` / `render_sidebar_nav` boilerplate from the originals so they keep their sidebar entry and won't break the password-gated app flow.

## Phase 6 — Audit & Deploy

- [ ] Step 6.1 / 6.2 / 6.3 / 6.4 / 6.5
