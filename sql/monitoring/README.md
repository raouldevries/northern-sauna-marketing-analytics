# Data Pipeline Monitoring

## Overview

Two monitoring layers:

1. **BQ scheduled query** — writes freshness data to `demo_monitoring.data_freshness_log` (used by Streamlit Data Quality page)
2. **Cloud Function** — runs 5 health checks daily, logs ERROR to Cloud Logging, triggers email alerts via Cloud Monitoring

## Cloud Function: `data-pipeline-monitor`

Runs daily at 09:00 CET via Cloud Scheduler. Checks:

| Check | What it catches | Severity |
|-------|----------------|----------|
| Data freshness | No new data in 3-5 days (per source threshold) | ERROR |
| Partition expiration | BQ Data Transfer re-sets 60-day expiration on `p_ads_*` tables | ERROR |
| Data gaps | Missing dates in the last 30 days (clamped to source start date) | ERROR |
| Transfer failures | FAILED/CANCELLED Google Ads transfer runs in last 7 days | ERROR |
| Historical datasets | GA4/SC historical tables exist with expected row counts | ERROR |

### Run manually

```bash
# Locally
python3 scripts/monitor_data_pipelines.py

# Via Cloud Scheduler
gcloud scheduler jobs run pipeline-monitor-trigger --project=demo-project --location=europe-west1
```

### Deploy

```bash
bash scripts/deploy.sh
```

### Configuration: live/historical split

Sources with both a live dataset (native export / bulk export) and a historical backfill dataset use two mechanisms to avoid false alerts:

- **`LIVE_START_DATES`** — The gap check only scans the live dataset from this date onward. Historical data is covered by the historical datasets check. Current: GA4 and Search Console from `2026-02-24`.
- **`HISTORICAL_DATASETS`** — The 5th check verifies that historical datasets still exist with a minimum number of tables and rows. Queries `__TABLES__` metadata only (zero cost).

### Configuration: known gaps

**`KNOWN_GAPS`** — Legitimate data gaps (e.g. no ad campaigns running) that should not trigger alerts. Currently: Meta Ads Apr–Aug 2025 (no campaigns active).

## Email alert setup (one-time, via Cloud Console)

### Step 1: Create notification channel

1. Go to [Cloud Monitoring → Alerting](https://console.cloud.google.com/monitoring/alerting?project=demo-project)
2. Click **Edit Notification Channels**
3. Under **Email**, click **Add New** → enter your email → **Save**

### Step 2: Create alert policy

1. Go to [Cloud Monitoring → Alerting](https://console.cloud.google.com/monitoring/alerting?project=demo-project)
2. Click **+ Create Policy**
3. **Add Condition:**
   - Resource type: `Cloud Run Revision`
   - Metric: `Log entries` (under `log_entry_count`)
   - Filter: `resource.labels.service_name = "data-pipeline-monitor" AND severity >= "ERROR"`
   - Condition: Any time series violates, is above 0, for 1 minute
4. **Notifications:** Select the email channel from Step 1
5. **Name:** `Data Pipeline Monitor — Check Failed`
6. Click **Create Policy**

### Alternative: Log-based alert (simpler)

1. Go to [Cloud Logging → Log Router](https://console.cloud.google.com/logs?project=demo-project)
2. Enter this filter:
   ```
   resource.type="cloud_run_revision"
   resource.labels.service_name="data-pipeline-monitor"
   severity>=ERROR
   ```
3. Click **Create Alert** (top-right)
4. Set notification to email, name the alert, save

## BQ Scheduled Query (freshness log)

Separate from the Cloud Function — writes to `demo_monitoring.data_freshness_log` for the Streamlit Data Quality page.

| Source | Dataset | Threshold |
|--------|---------|-----------|
| GA4 native export | `analytics_000000000` | 3 days |
| Google Ads (main) | `google_ads` | 3 days |
| Google Ads PMax/RSA assets | `google_ads_pmax` | 3 days |
| Search Console | `searchconsole` | 5 days |
| Meta Ads | `meta_ads` | 3 days |
| GMB Reviews | `demo_data` | 8 days |

GMB freshness uses `DATE(MAX(imported_at))` (sync run timestamp) rather
than `review_create_time` / `review_update_time`. The latter reflect when
reviewers wrote the review and would still look "recent" if the sync
itself stalled.

### Quick check

```sql
SELECT * FROM `demo-project.demo_monitoring.v_data_freshness`
SELECT * FROM `demo-project.demo_monitoring.v_data_freshness` WHERE status = 'STALE'
```

### Set up scheduled query (one-time, via BQ Console)

1. Go to [BigQuery Console](https://console.cloud.google.com/bigquery?project=demo-project)
2. Click **Scheduled Queries** in left sidebar → **+ Create Scheduled Query**
3. Settings:
   - **Name:** `data-freshness-check`
   - **Schedule:** Every day at `09:00 UTC`
   - **Destination:** `demo_monitoring.data_freshness_log` (Write preference: Overwrite)
4. Paste the contents of `data_freshness_check.sql` into the query editor
5. Click **Save** → Authorize with Google
