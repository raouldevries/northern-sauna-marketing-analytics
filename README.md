# Northern Sauna Marketing Analytics — Public Demo

A Streamlit dashboard that consolidates bookings, paid media, organic search, and customer behaviour into a single operational view. Built as the public, synthetic-data face of an internal analytics platform.

> **This is a portfolio piece.** Every number in the deployed demo is generated from `scripts/generate_demo_data.py` — there are no real customers, no real revenue, no real campaigns.

**Live demo:** [northern-sauna-marketing-analytics.streamlit.app](https://northern-sauna-marketing-analytics.streamlit.app/) (no password — `DEMO_MODE=true` short-circuits the auth gate).

![Marketing page — cross-channel KPIs](docs/screenshots/marketing-overview.png)

## How this was built

This codebase is also a portfolio of an agentic engineering practice. Most of the work landed through structured Claude Code workflows, captured in the repo:

- **10 audit-loop cycles** documented in [`docs/progress.md`](docs/progress.md), each with self-audit sub-agent findings + Codex CLI external review + per-finding triage. Every plan step was tested, audited, fixed, and committed under a stop-hook that enforces the cycle.
- **Per-session handover docs** live in [`docs/handovers/`](docs/handovers/) so the work survived multiple sessions without context loss.
- **A pre-commit identifier gate** (`scripts/validate_identifiers.sh`) blocks any commit that would leak real-world identifiers (GCP project ID, GA4 property ID, owner email, internal dataset names, Dutch UI strings from the live build) into a public push. Run continuously throughout the project; caught the regressions you don't catch by eye.
- **A Chrome-driven deployed-app audit** (cycle #10) clicked through every page on the live URL and caught three Dutch UI labels that AppTest smoke + identifier scrub had both missed.

### Skills, plugins, and tools used

The build leans on a small, sharp set of Claude Code workflows + external integrations rather than a long list. Everything below was used at least once during the project; the cycle-by-cycle log in [`docs/progress.md`](docs/progress.md) shows exactly where.

| | What | Where it shows up |
|---|---|---|
| Skill | **`/plan-loop`** | Converged the multi-phase implementation plan against the codebase across 4 iterations before any code landed. The full plan lives in the private repo; the per-phase outcomes are in [`docs/progress.md`](docs/progress.md). |
| Skill | **`/audit-loop`** | Ran every plan step through test/gate → validate → self-audit subagent → Codex external review → triage → commit, under a stop-hook. 10 cycles end-to-end. |
| Skill | **`/handover`** | Produced 6 handover docs in [`docs/handovers/`](docs/handovers/) (private repo) so the multi-day build survived between sessions. |
| Tool | **Codex CLI** (`codex exec --sandbox read-only`) | Independent external reviewer inside every audit-loop cycle. Read-only sandbox mode means it can grep / `git diff` but can't write — its findings come back as a triage list, not a patch. |
| Subagent | **General-purpose self-audit subagent** | The internal reviewer that runs before Codex on each cycle. Isolated from the main context so the review is genuinely independent — catches things you've stopped seeing because you wrote them. |
| Plugin | **`claude-in-chrome` MCP** | Drove the deployed-app audit (cycle #10). Clicked through every page on the live Streamlit Cloud URL, queried the DOM, and caught three Dutch UI labels surviving on the Marketing → CPA Targets tab that AppTest smoke + the identifier gate had both missed. |
| Custom | **Identifier gate** (`scripts/validate_identifiers.sh`) | ~30 banned tokens covering brand, real venue names, Dutch UI strings, GCP project ID, GA4 property ID, owner email. Exits non-zero on any hit. Local-only — not a GitHub Action — but invoked at the top of every audit-loop cycle. |

If you're evaluating this as a work sample, [`docs/progress.md`](docs/progress.md) is the most differentiated artifact in the repo — it shows what each cycle's audit subagent found, what Codex flagged independently, how each finding was triaged (FIX / DOCUMENT / DISMISS), and what landed in the commit.

## Architecture

```
SOURCES                    SYNC                  STORAGE          FRONTEND

Bookeo        ──────────>  Cloud Function  ──╮
GA4           ──────────>  BQ Export+API   ──┤
Search Console ─────────>  Bulk Export     ──┤  BigQuery  ──>  Streamlit
Google Ads    ──────────>  BQ Transfer     ──┤
Meta Ads      ──────────>  Airbyte         ──╯
```

In the public demo, the `BigQuery` block is swapped for `demo_data/*.csv` and the warehouse path is short-circuited by a single environment variable (`DEMO_MODE=true`). No secrets are read, no network calls are made.

### What's *not* in the public demo

- Real customer text, reviews, ad creative, or revenue.
- The Anthropic API key and the natural-language SQL surface (the "Northern Sauna AI" page is a live-build-only stub).
- The Google Business Profile review ingest (the Reviews page is a live-build-only stub).
- The BigQuery `gcp_service_account` secret.
- The catalog-driven SQL safety validator, schema-drift detector, and the Bookeo ingestion pipeline — these live in the private repo where they're load-bearing.

Each exclusion is either a security boundary (secrets) or a data-authenticity decision (real text is real text). The two stub pages render a text-only "Live build only" panel explaining the dependency.

## Analytics depth

The dashboard isn't just charts on top of a warehouse. The underlying modeling, visible in `streamlit/features/`:

- **Customer Lifetime Value** with multi-cohort retention (per-segment New/Regular/VIP), 12-month rolling window, segment-aware annual frequency, ROAS variants for both raw conversion value and projected CLV.
- **CPA targeting** decomposed into operating-costs % + profit-margin % levers, with break-even (current-AOV) and target-profit (CLV-projected) variants per location.
- **Cross-channel ROI + multi-touch attribution** via the See-Think-Do-Care framework — campaign objectives are classified by phase and ROI is computed against the correct conversion definition for each phase.
- **STDC location performance with weighted multi-location attribution** — ad-sets like "Clicks | All locations" get split across the underlying venues by ad-set weight; city-cluster campaigns (e.g., "Helsinki city") split across cluster members.

Most "marketing analytics portfolio" projects stop at impressions and clicks. The CLV ROAS and 2Y CLV Value KPIs in the screenshot above are computed against the modeling layer.

## Production-engineering details worth a peek

- **Live-build/demo path parity.** One shared helper (`_load_fixture` in `streamlit/data/queries.py`) does CSV read + Timestamp coercion + inclusive date filter so the demo path matches BigQuery's `to_dataframe()` dtype contract. Pages that call `.strftime()` or `.dt.date` on a date column work identically on both paths.
- **Idempotent BigQuery sync** with 7-day overlap + MERGE upsert so re-runs are safe; three Bookeo accounts processed in parallel via `ThreadPoolExecutor`.
- **Catalog-driven SQL safety** (live build only) — every LLM-generated query goes through a validator that whitelists tables, enforces partition filters on dated tables, and caps `maximum_bytes_billed`. The catalog (`schema_catalog.yaml`) is the single source of truth for what the model can see.
- **Schema drift detection** — a scheduled job compares the catalog against live BigQuery; clean / drift / error exit codes for the runbook.

## Pages

| Page | What it shows |
|---|---|
| Overview | Cross-channel KPIs, data-freshness banner, feedback inbox |
| Turnover | Revenue by location, weekday/weekend split, time-of-day heatmap |
| Customers | Cohort analysis, repeat-rate, lifetime value |
| Members | Membership churn, end-date forecasting, member vs non-member economics |
| Capacity | Per-location occupancy, peak-slot detection |
| Promotions | Discount-code performance, attribution to repeat bookings |
| Marketing | Cross-channel ROI, CPA by location, age / gender / device / platform / network / search-position breakdowns |
| Reviews | _Live-build-only stub — see the page for why_ |
| Bookings | Raw booking explorer with filters |
| Organic & SEO | GA4 traffic + Search Console queries / pages |
| Northern Sauna AI | _Live-build-only stub — natural-language SQL against the warehouse_ |
| About Northern Sauna AI | Static explainer of the agent architecture |

## Stack

- **Frontend:** Streamlit (Python), custom theming on the chart system.
- **Warehouse (live build):** BigQuery in `europe-west4`.
- **Data sources (live build):** Bookeo (three accounts merged) + Google Ads BigQuery Data Transfer (two datasets, `google_ads` + `google_ads_pmax`) + Meta Ads via Airbyte + GA4 Data API + GA4 BigQuery export + Search Console bulk export + Search Console API backfill + Google Business Profile API.
- **Analytics agent (live build only):** Claude via the Anthropic API.

## Run locally

Requires Python 3.11+.

```bash
git clone https://github.com/raouldevries/northern-sauna-marketing-analytics
cd northern-sauna-marketing-analytics

python -m venv .venv
source .venv/bin/activate
pip install -r streamlit/requirements.txt

# Optional: regenerate the demo fixtures (deterministic — same SHA every run)
python scripts/generate_demo_data.py --out demo_data/

DEMO_MODE=true streamlit run streamlit/app.py
```

Open `http://localhost:8501`. The auth gate auto-bypasses in demo mode.

## How the demo data is generated

`scripts/generate_demo_data.py` is a single deterministic generator (seeded `Faker(42)` + `numpy.random.default_rng(42)`) that emits 15 CSVs covering ~14 months of bookings, ad spend, organic traffic, and search queries. Two consecutive runs produce byte-identical output, verified by hashing all 15 CSVs into a single sha-of-shas. Every fixture passes inline assertions on row counts, ratios, and cross-fixture attribution (e.g., total ad conversions never exceed total non-canceled bookings). Full schema in [`docs/fixtures.md`](docs/fixtures.md).

Venue names that appear in mapping tables and SQL views ("Northern Sauna Stockholm Östermalm", "Helsinki Kamppi", "Oslo Grünerløkka") are the *shape* of the live build's location-normalization logic. The demo CSVs use a flat city-level set — Northern Sauna Stockholm / Helsinki / Oslo / Copenhagen / Gothenburg / Bergen — so nothing in the data corresponds to a real venue.

## Repo layout

```
streamlit/
  app.py                       # entry point + auth + sidebar
  pages/                       # 12 Streamlit pages
  components/                  # reusable UI bits (live-build stub, demo banner)
  data/                        # query layer (BigQuery in live, fixtures in demo)
  features/                    # CLV, CPA, STDC, attribution modeling
demo_data/                     # 15 deterministic CSV fixtures
scripts/
  generate_demo_data.py        # the synthetic generator
  validate_identifiers.sh      # the identifier gate
sql/                           # warehouse DDL and views
docs/
  progress.md                  # full plan progress + audit-loop notes
  handovers/                   # per-session handover docs
  fixtures.md                  # fixture schema catalog
  screenshots/                 # README assets
```

## Licence

This repository is a portfolio piece. No reuse licence is granted; reach out if you'd like to discuss the code.
