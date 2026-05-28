#!/usr/bin/env python3
"""Generate synthetic CSV fixtures for the public demo.

Phase 3 of the demo-showcase plan. Reads the schema contract in
``docs/fixtures.md`` and writes deterministic CSVs to ``demo_data/`` that
the Phase 4 loaders consume when ``DEMO_MODE=true``.

Produces all 15 demo fixtures in one run (Steps 3.2 / 3.3 / 3.4):
bookings.csv plus the marketing, GA4, and Search Console satellites.

Usage:
    python scripts/generate_demo_data.py --out demo_data/

Determinism:
    Faker(seed=42) + numpy.random.default_rng(42). Two runs on the same
    machine produce byte-identical CSVs.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# ---------------------------------------------------------------------------
# Stylized constants — see docs/fixtures.md
# ---------------------------------------------------------------------------

UNIT_PRICE_EUR = 99.0
VAT_RATE = 0.21

# Average bookings per location per weekday. Weekend (Sat/Sun) gets a 20%
# lift. Tuned so the 12-month bookings.csv lands in the 3,000-8,000 range
# specified by the plan.
# Six locations across Sweden, Norway, Finland, Denmark — reads like a real
# expanding Nordic chain. Baselines vary so the "Turnover by Location" chart
# tells a story: Stockholm (flagship) > capitals (Helsinki / Oslo / Copenhagen)
# > regional sites (Gothenburg / Bergen).
BASELINE_PER_DAY = {
    "stockholm": 4,
    "helsinki": 3,
    "oslo": 3,
    "copenhagen": 3,
    "gothenburg": 2,
    "bergen": 2,
}
WEEKEND_LIFT = 1.20

CANCEL_RATE = 0.05
NO_SHOW_RATE = 0.02
MEMBER_RATIO = 0.50

# Visible product catalog. Kept tiny + obviously generic.
PRODUCT_CATALOG = [
    ("Sauna 60 min", 60),
    ("Sauna 90 min", 90),
    ("Sauna 120 min", 120),
]

PROMOTION_NAMES = ["Spring offer", "Member discount"]
# Realistic source mix for a wellness / pop-up sauna business: paid + social
# discovery dominate top-of-funnel, repeat customers come back via direct +
# newsletter, gift-card redemptions and word-of-mouth round out the long tail.
# Weights sum to 1.0 — bookings still get a small `None` slice below for the
# genuinely-untracked sessions (matches what most real booking systems see).
BOOKING_SOURCES = [
    "direct",
    "google",
    "instagram",
    "facebook",
    "referral",
    "newsletter",
    "gift_card",
    "affiliate",
]
BOOKING_SOURCE_WEIGHTS = [0.22, 0.26, 0.16, 0.09, 0.11, 0.06, 0.06, 0.04]

# Raw location strings (pre-mapping). These match the keys in
# streamlit/data/bq_client.py::_BQ_TO_STREAMLIT_LOCATION on the demo side.
LOCATION_BY_ACCOUNT = {
    "stockholm": "Northern Sauna Stockholm",
    "helsinki": "Northern Sauna Helsinki",
    "oslo": "Northern Sauna Oslo",
    "copenhagen": "Northern Sauna Copenhagen",
    "gothenburg": "Northern Sauna Gothenburg",
    "bergen": "Northern Sauna Bergen",
}

# ---------------------------------------------------------------------------
# Stylized constants — marketing
# ---------------------------------------------------------------------------

DAILY_SPEND_PER_CAMPAIGN = 100.0  # €/day/campaign
CPC = 1.0                          # cost per click
CTR = 0.02                         # click-through rate
# CVR tuned so total campaign conversions stay strictly below total
# non-canceled bookings (plan: "no impossible attribution"). With 7
# campaigns × 100 clicks/day × 0.02 = 14 conv/day, ~5k/year ≤ ~5.8k bookings.
CVR = 0.02
CONV_VALUE = 50.0                  # avg conversion value (€)

GOOGLE_CAMPAIGNS = [
    ("Demo Search Brand", "SEARCH"),
    ("Demo Search Generic", "SEARCH"),
    ("Demo Display Retargeting", "CONTENT"),
]
META_CAMPAIGNS = [
    ("Demo Meta Awareness Q1", "AWARENESS"),
    ("Demo Meta Awareness Q2", "AWARENESS"),
    ("Demo Meta Conversion Q1", "CONVERSIONS"),
    ("Demo Meta Conversion Q2", "CONVERSIONS"),
]

# Demographic distributions
AGE_BUCKETS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
AGE_WEIGHTS = [0.10, 0.25, 0.25, 0.18, 0.15, 0.07]  # slight skew to 25-44
GENDER_WEIGHTS = {"female": 0.60, "male": 0.40}
DEVICE_WEIGHTS = {"Mobile": 0.70, "Desktop": 0.20, "Tablet": 0.08, "Other": 0.02}

# Raw enum values from the live BQ tables — pages 7 (Marketing) filter on
# these exact strings (e.g., `_plat_agg[_plat_agg["publisher_platform"] == "facebook"]`,
# `_gn["network"] == "SEARCH"`, `_tk_pos["slot"] == "SEARCH_TOP"`). Title-case
# variants silently produce empty filter results and miss takeaway sections.
META_PUBLISHER_PLATFORMS = ["facebook", "instagram", "audience_network"]
META_PLATFORM_POSITIONS = ["feed", "feed_stories", "stories", "reels", "marketplace"]
GOOGLE_NETWORK_SPLIT = {"SEARCH": 0.70, "CONTENT": 0.30}
GOOGLE_SEARCH_SLOTS = {"SEARCH_TOP": 0.65, "SEARCH_OTHER": 0.35}

# ---------------------------------------------------------------------------
# Stylized constants — GA4 + Search Console
# ---------------------------------------------------------------------------

GA4_SOURCE_MEDIUM = [
    ("google", "organic", "Organic Search"),
    ("google", "cpc", "Paid Search"),
    ("(direct)", "(none)", "Direct"),
    ("facebook.com", "social", "Organic Social"),
    ("newsletter", "email", "Email"),
]
GA4_BASELINE_SESSIONS = 200            # per source-medium combo per weekday
GA4_PAGES_PER_SESSION = 3
GA4_AVG_SESSION_DURATION = 90.0        # seconds
GA4_ENGAGEMENT_RATE = 0.60

SC_QUERY_TERMS = [
    "sauna near me",
    "northern sauna stockholm",
    "northern sauna helsinki",
    "northern sauna oslo",
    "northern sauna copenhagen",
    "northern sauna gothenburg",
    "northern sauna bergen",
    "outdoor sauna booking",
    "wood-fired sauna",
    "popup sauna",
]
SC_PAGES = [
    "/", "/booking", "/about", "/contact",
    "/locations/stockholm", "/locations/helsinki", "/locations/oslo",
    "/locations/copenhagen", "/locations/gothenburg", "/locations/bergen",
    "/pricing", "/membership", "/blog",
]

# ---------------------------------------------------------------------------
# Column tuples — order must match the loader bodies in queries.py
# ---------------------------------------------------------------------------

# Exact column order expected by streamlit/data/queries.py::_query_bookings
# (matches the SELECT-list of BOOKINGS_QUERY_SELECT_COLUMNS).
BOOKINGS_COLUMNS = (
    "id",
    "source_account",
    "customer_email",
    "customer_name",
    "customer_phone",
    "location",
    "product_name",
    "booking_created_at",
    "visit_datetime",
    "status",
    "participants",
    "gross_amount",
    "net_amount",
    "paid_amount",
    "end_time",
    "promotion_name",
    "booking_source",
    "private_event",
    "is_canceled",
    "cancelation_time",
    "cancelation_agent",
    "creation_agent",
    "last_change_time",
    "last_change_agent",
    "is_no_show",
    "coupon_codes_json",
    "is_member",
    "membership_end",
)

CAMPAIGN_PERF_COLUMNS = (
    "date", "platform", "campaign_name", "impressions", "clicks", "spend",
    "ctr", "cpc", "conversions", "conversion_value", "reach",
)

LOCATION_PERF_COLUMNS = (
    "date", "location",
    "bookings", "bookings_total", "bookings_excl_canceled", "participants",
    "revenue", "revenue_excl_canceled",
    "google_ads_clicks", "google_ads_impressions", "google_ads_spend",
    "google_ads_conversions", "google_ads_conversion_value",
    "meta_ads_clicks", "meta_ads_impressions", "meta_ads_spend",
    "meta_ads_conversions", "meta_ads_conversion_value",
)

AGE_DEMO_COLUMNS = (
    "platform", "age_group", "impressions", "clicks", "spend", "conversions", "conversion_value",
)

GENDER_DEMO_COLUMNS = (
    "platform", "gender", "impressions", "clicks", "spend",
    "conversions", "conversion_value", "cpc", "ctr",
)

DEVICE_DEMO_COLUMNS = (
    "platform", "device", "impressions", "clicks", "spend", "conversions", "conversion_value",
)

PLATFORM_PLACEMENT_COLUMNS = (
    "publisher_platform", "platform_position",
    "impressions", "clicks", "spend", "reach", "cpc", "ctr",
)

GADS_NETWORK_COLUMNS = (
    "network", "impressions", "clicks", "spend",
    "conversions", "conversion_value", "cpc", "ctr", "cpa",
)

GADS_CAMPAIGN_NETWORK_COLUMNS = (
    "campaign_name", "network", "impressions", "clicks", "spend",
    "conversions", "ctr", "cpa",
)

GADS_SEARCH_POSITION_COLUMNS = (
    "slot", "impressions", "clicks", "spend", "conversions", "ctr", "cpa",
)

DAILY_SUMMARY_COLUMNS = (
    "date", "source", "impressions", "clicks", "spend", "sessions", "conversions",
)

GA4_TRAFFIC_COLUMNS = (
    "date", "session_source", "session_medium", "session_default_channel_group",
    "sessions", "total_users", "new_users",
    "engaged_sessions", "engagement_rate", "screen_page_views", "average_session_duration",
)

SC_QUERIES_COLUMNS = (
    "data_date", "query", "clicks", "impressions", "avg_position", "ctr",
)

SC_PAGES_COLUMNS = (
    "data_date", "url", "clicks", "impressions", "avg_position",
)

FAKER_SEED = 42
RNG_SEED = 42


def _date_range(start: date, end: date) -> list[date]:
    """Inclusive list of dates in [start, end]."""
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def _bookings_for_day(account: str, day: date, rng: np.random.Generator) -> int:
    """Return the number of bookings to draw for one location on one day."""
    base = BASELINE_PER_DAY[account]
    lift = WEEKEND_LIFT if day.weekday() >= 5 else 1.0
    # Poisson around the lifted baseline so daily counts look natural but
    # the long-run mean is stylized.
    return int(rng.poisson(base * lift))


def _draw_status(rng: np.random.Generator) -> str:
    r = rng.random()
    if r < CANCEL_RATE:
        return "canceled"
    if r < CANCEL_RATE + NO_SHOW_RATE:
        return "no_show"
    return "completed"


def _draw_participants(rng: np.random.Generator) -> int:
    # 1-6 with a slight skew toward 2-3 (a typical pair / small-group session).
    return int(rng.choice([1, 2, 3, 4, 5, 6], p=[0.08, 0.30, 0.30, 0.18, 0.10, 0.04]))


def _draw_product(rng: np.random.Generator) -> tuple[str, int]:
    return PRODUCT_CATALOG[int(rng.integers(0, len(PRODUCT_CATALOG)))]


def _customer_email(name: str, account: str, ix: int) -> str:
    # Deterministic, obviously synthetic. Never accidentally resembles a real
    # email — the @example.com suffix is IANA-reserved.
    safe = "".join(ch.lower() if ch.isalnum() else "" for ch in name)[:12]
    return f"customer_{safe}_{account}_{ix:05d}@example.com"


def _build_bookings(
    start: date,
    end: date,
    faker: Faker,
    rng: np.random.Generator,
) -> pd.DataFrame:
    rows: list[dict] = []
    per_account_counter = {acc: 0 for acc in BASELINE_PER_DAY}
    days = _date_range(start, end)

    for day in days:
        for account in BASELINE_PER_DAY:
            n = _bookings_for_day(account, day, rng)
            for _ in range(n):
                per_account_counter[account] += 1
                counter = per_account_counter[account]
                booking_id = f"bookeo_{account}_{counter:06d}"

                name = faker.name()
                email = _customer_email(name, account, counter)
                phone = faker.phone_number()

                product_name, product_duration_min = _draw_product(rng)
                participants = _draw_participants(rng)
                gross = round(participants * UNIT_PRICE_EUR, 2)
                net = round(gross / (1 + VAT_RATE), 2)

                # Visit time: 08:00–22:00 with a realistic evening peak. After-
                # work hours (17-20) are when wellness customers actually book
                # the slot; morning slots are sparse but non-empty (early-bird
                # and weekend brunch saunas).
                visit_hour = int(rng.choice(
                    list(range(8, 23)),
                    p=[
                        0.02, 0.03, 0.04, 0.05, 0.05, 0.05,  # 08-13
                        0.06, 0.07, 0.08,                     # 14-16
                        0.12, 0.13, 0.12,                     # 17-19 (peak)
                        0.09, 0.06, 0.03,                     # 20-22
                    ],
                ))
                visit_minute = int(rng.choice([0, 15, 30, 45]))
                visit_dt = datetime.combine(
                    day, time(hour=visit_hour, minute=visit_minute)
                )
                end_dt = visit_dt + timedelta(minutes=product_duration_min)

                # Booking creation: 0-60 days before visit, with an independent
                # hour drawn from the full 24h weighted distribution below. This
                # is when the customer was on the booking site — distinct from
                # the visit_hour they booked FOR. Late-night and early-morning
                # browsing are real (phone-in-bed sessions), the 12:00 lunch
                # spike + 20:00 after-dinner peak are the heaviest bands.
                lead_days = int(rng.integers(0, 61))
                # 24-hour weight curve, normalized at module load.
                _CREATION_HOUR_WEIGHTS = (
                    2, 2, 1, 1, 1, 1,    # 00-05  late night → sleep
                    1, 2, 4, 5, 5, 6,    # 06-11  morning ramp
                    7, 6, 5, 5, 5, 5,    # 12-17  lunch spike + afternoon
                    6, 8, 9, 8, 5, 3,    # 18-23  evening peak at 20:00
                )
                _total_w = sum(_CREATION_HOUR_WEIGHTS)
                _creation_probs = [w / _total_w for w in _CREATION_HOUR_WEIGHTS]
                created_hour = int(rng.choice(list(range(24)), p=_creation_probs))
                created_minute = int(rng.integers(0, 60))
                visit_date_only = visit_dt.date()
                created_date = visit_date_only - timedelta(days=lead_days)
                created_dt = datetime.combine(
                    created_date,
                    time(hour=created_hour, minute=created_minute),
                )
                # Same-day bookings created after the visit hour aren't physically
                # possible — clamp to a believable 1-3 hours before the visit.
                if created_dt >= visit_dt:
                    created_dt = visit_dt - timedelta(hours=int(rng.integers(1, 4)))

                status = _draw_status(rng)
                is_canceled = status == "canceled"
                is_no_show = status == "no_show"
                paid = 0.0 if is_canceled else net

                cancel_time: str | None = None
                cancel_agent: str | None = None
                last_change_agent = "system"
                if is_canceled:
                    # Cancellation happens 0-7 days after creation, before visit.
                    delay = int(rng.integers(0, 8))
                    cancel_dt = min(created_dt + timedelta(days=delay), visit_dt)
                    cancel_time = cancel_dt.isoformat()
                    cancel_agent = "customer"
                    last_change_agent = "customer"

                # Promotion / source: mostly NULL.
                promotion = (
                    PROMOTION_NAMES[int(rng.integers(0, len(PROMOTION_NAMES)))]
                    if rng.random() < 0.20
                    else None
                )
                # ~8% have no source recorded (genuinely untracked / sessions
                # that lost the referrer). The rest are weighted across the
                # realistic source mix above.
                source = (
                    str(rng.choice(BOOKING_SOURCES, p=BOOKING_SOURCE_WEIGHTS))
                    if rng.random() < 0.92
                    else None
                )

                is_member = bool(rng.random() < MEMBER_RATIO)
                membership_end: str | None = None
                if is_member:
                    membership_end = (day + timedelta(days=int(rng.integers(1, 365)))).isoformat()

                rows.append(
                    {
                        "id": booking_id,
                        "source_account": account,
                        "customer_email": email,
                        "customer_name": name,
                        "customer_phone": phone,
                        "location": LOCATION_BY_ACCOUNT[account],
                        "product_name": product_name,
                        "booking_created_at": created_dt.isoformat(),
                        "visit_datetime": visit_dt.isoformat(),
                        "status": status,
                        "participants": participants,
                        "gross_amount": gross,
                        "net_amount": net,
                        "paid_amount": paid,
                        "end_time": end_dt.isoformat(),
                        "promotion_name": promotion,
                        "booking_source": source,
                        "private_event": "false",
                        "is_canceled": str(is_canceled).lower(),
                        "cancelation_time": cancel_time,
                        "cancelation_agent": cancel_agent,
                        "creation_agent": "system",
                        "last_change_time": (cancel_time or created_dt.isoformat()),
                        "last_change_agent": last_change_agent,
                        "is_no_show": str(is_no_show).lower(),
                        "coupon_codes_json": json.dumps([]),
                        "is_member": is_member,
                        "membership_end": membership_end,
                    }
                )

    df = pd.DataFrame(rows, columns=list(BOOKINGS_COLUMNS))
    return df


def _validate_bookings(df: pd.DataFrame) -> None:
    """Inline assertions — fail fast if the generator drifts from the schema."""
    assert tuple(df.columns) == BOOKINGS_COLUMNS, (
        f"column drift:\n  expected {BOOKINGS_COLUMNS}\n  got      {tuple(df.columns)}"
    )
    n = len(df)
    assert 3000 <= n <= 8000, f"bookings.csv row count {n} outside plan target 3000-8000"
    # Sanity: every account appears.
    assert set(df["source_account"].unique()) == set(BASELINE_PER_DAY), (
        f"missing account(s): {set(BASELINE_PER_DAY) - set(df['source_account'].unique())}"
    )
    # Sanity: gross is exactly participants * €99.
    derived = df["participants"] * UNIT_PRICE_EUR
    assert np.allclose(df["gross_amount"], derived), (
        "gross_amount drift from participants * unit price"
    )
    # Sanity: member ratio within ±5% of stylized constant.
    actual_member_ratio = df["is_member"].mean()
    assert abs(actual_member_ratio - MEMBER_RATIO) < 0.05, (
        f"member ratio {actual_member_ratio:.2%} drifted from stylized {MEMBER_RATIO:.0%} target"
    )


# ---------------------------------------------------------------------------
# Marketing fixtures — campaign performance + breakouts
# ---------------------------------------------------------------------------

def _weekend_lift(d: date) -> float:
    return WEEKEND_LIFT if d.weekday() >= 5 else 1.0


def _round_int(x: float) -> int:
    return int(round(x))


def _build_campaign_performance(
    start: date,
    end: date,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Daily metrics per campaign. Stylized: €100/day baseline, CTR=2%, CPC=€1, CVR=5%."""
    rows = []
    days = _date_range(start, end)
    campaigns = (
        [("google", name, obj) for name, obj in GOOGLE_CAMPAIGNS]
        + [("meta", name, obj) for name, obj in META_CAMPAIGNS]
    )
    for day in days:
        lift = _weekend_lift(day)
        for platform, campaign_name, _objective in campaigns:
            # Mild per-campaign jitter so charts aren't flat lines.
            jitter = 1.0 + (rng.random() - 0.5) * 0.20  # ±10%
            spend = round(DAILY_SPEND_PER_CAMPAIGN * lift * jitter, 2)
            clicks = _round_int(spend / CPC)
            impressions = _round_int(clicks / CTR)
            conversions = _round_int(clicks * CVR)
            conversion_value = round(conversions * CONV_VALUE, 2)
            ctr_val = clicks / impressions if impressions else 0.0
            cpc_val = spend / clicks if clicks else 0.0
            reach = _round_int(impressions * 0.85) if platform == "meta" else None
            rows.append({
                "date": day.isoformat(),
                "platform": platform,
                "campaign_name": campaign_name,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "ctr": round(ctr_val, 4),
                "cpc": round(cpc_val, 2),
                "conversions": conversions,
                "conversion_value": conversion_value,
                "reach": reach,
            })
    return pd.DataFrame(rows, columns=list(CAMPAIGN_PERF_COLUMNS))


def _validate_campaign_performance(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == CAMPAIGN_PERF_COLUMNS
    assert df["platform"].isin({"google", "meta"}).all()
    # Internal consistency: spend ≈ clicks * CPC, clicks ≈ impressions * CTR,
    # conversions ≈ clicks * CVR (each within ±1 due to _round_int).
    diff_spend = (df["spend"] - df["clicks"] * CPC).abs()
    assert diff_spend.max() < 1.0, f"spend/clicks/CPC drift, max diff {diff_spend.max():.2f}"
    diff_clicks = (df["clicks"] - df["impressions"] * CTR).abs()
    assert diff_clicks.max() < 1.0, (
        f"clicks/impressions/CTR drift, max diff {diff_clicks.max():.2f}"
    )
    diff_conv = (df["conversions"] - df["clicks"] * CVR).abs()
    assert diff_conv.max() < 1.0, f"conversions/clicks/CVR drift, max diff {diff_conv.max():.2f}"
    # Reach only for Meta rows.
    assert df.loc[df["platform"] == "google", "reach"].isna().all()
    assert df.loc[df["platform"] == "meta", "reach"].notna().all()


def _build_location_performance(
    bookings_df: pd.DataFrame,
    campaign_df: pd.DataFrame,
    locations: tuple[str, ...] = (
        "Northern Sauna Stockholm",
        "Northern Sauna Helsinki",
        "Northern Sauna Oslo",
        "Northern Sauna Copenhagen",
        "Northern Sauna Gothenburg",
        "Northern Sauna Bergen",
    ),
    do_filter: bool = False,
) -> pd.DataFrame:
    """Aggregate bookings + allocate ad metrics across 3 locations equally.

    If do_filter is True, only the conversion-stage subset is used (Meta
    CONVERSIONS + Google Search campaigns), matching v_location_performance_do.
    """
    b = bookings_df.copy()
    b["date"] = pd.to_datetime(b["visit_datetime"]).dt.date.astype(str)
    grouped = b.groupby(["date", "location"]).agg(
        bookings_total=("id", "count"),
        bookings_excl_canceled=("status", lambda s: int((s != "canceled").sum())),
        participants=("participants", "sum"),
        revenue=("net_amount", "sum"),
        revenue_excl_canceled=("paid_amount", "sum"),
    ).reset_index()

    # Ad allocation: split campaign aggregates equally across the 3 locations.
    cp = campaign_df.copy()
    if do_filter:
        # DO stage: Google Search + Meta CONVERSIONS only.
        google_do = {n for n, obj in GOOGLE_CAMPAIGNS if obj == "SEARCH"}
        meta_do = {n for n, obj in META_CAMPAIGNS if obj == "CONVERSIONS"}
        cp = cp[cp["campaign_name"].isin(google_do | meta_do)]
    cp_daily = cp.groupby(["date", "platform"]).agg(
        clicks=("clicks", "sum"),
        impressions=("impressions", "sum"),
        spend=("spend", "sum"),
        conversions=("conversions", "sum"),
        conversion_value=("conversion_value", "sum"),
    ).reset_index()

    n_locations = len(locations)

    def _alloc_int(src, key: str) -> int:
        return _round_int(src[key] / n_locations) if src is not None else 0

    def _alloc_float(src, key: str) -> float:
        return round(src[key] / n_locations, 2) if src is not None else 0.0

    rows = []
    for day in grouped["date"].unique():
        google = cp_daily[(cp_daily["date"] == day) & (cp_daily["platform"] == "google")]
        meta = cp_daily[(cp_daily["date"] == day) & (cp_daily["platform"] == "meta")]
        g = google.iloc[0] if len(google) else None
        m = meta.iloc[0] if len(meta) else None
        for loc in locations:
            sub = grouped[(grouped["date"] == day) & (grouped["location"] == loc)]
            if sub.empty:
                continue
            r = sub.iloc[0]
            rows.append({
                "date": day,
                "location": loc,
                "bookings": int(r["bookings_total"]),
                "bookings_total": int(r["bookings_total"]),
                "bookings_excl_canceled": int(r["bookings_excl_canceled"]),
                "participants": int(r["participants"]),
                "revenue": float(r["revenue"]),
                "revenue_excl_canceled": float(r["revenue_excl_canceled"]),
                "google_ads_clicks": _alloc_int(g, "clicks"),
                "google_ads_impressions": _alloc_int(g, "impressions"),
                "google_ads_spend": _alloc_float(g, "spend"),
                "google_ads_conversions": _alloc_int(g, "conversions"),
                "google_ads_conversion_value": _alloc_float(g, "conversion_value"),
                "meta_ads_clicks": _alloc_int(m, "clicks"),
                "meta_ads_impressions": _alloc_int(m, "impressions"),
                "meta_ads_spend": _alloc_float(m, "spend"),
                "meta_ads_conversions": _alloc_int(m, "conversions"),
                "meta_ads_conversion_value": _alloc_float(m, "conversion_value"),
            })
    return pd.DataFrame(rows, columns=list(LOCATION_PERF_COLUMNS))


def _validate_location_performance(df: pd.DataFrame, label: str = "location_perf") -> None:
    assert tuple(df.columns) == LOCATION_PERF_COLUMNS, f"{label}: column drift"
    assert df["location"].isin({
        "Northern Sauna Stockholm",
        "Northern Sauna Helsinki",
        "Northern Sauna Oslo",
        "Northern Sauna Copenhagen",
        "Northern Sauna Gothenburg",
        "Northern Sauna Bergen",
    }).all()
    assert (df["bookings"] == df["bookings_total"]).all(), (
        f"{label}: bookings/bookings_total mismatch"
    )
    assert (df["bookings_excl_canceled"] <= df["bookings_total"]).all()
    assert (df["revenue"] >= 0).all()


def _build_age_demographics(
    campaign_df: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Age × platform breakdown. Conversions/conversion_value are 0 for Meta (no source data)."""
    google_totals = campaign_df[campaign_df["platform"] == "google"][
        ["impressions", "clicks", "spend", "conversions", "conversion_value"]
    ].sum()
    meta_totals = campaign_df[campaign_df["platform"] == "meta"][
        ["impressions", "clicks", "spend"]
    ].sum()
    rows = []
    for platform, totals, has_conv in [
        ("Google Ads", google_totals, True),
        ("Meta Ads", meta_totals, False),
    ]:
        for age, w in zip(AGE_BUCKETS, AGE_WEIGHTS):
            impressions = _round_int(totals["impressions"] * w)
            clicks = _round_int(totals["clicks"] * w)
            spend = round(totals["spend"] * w, 2)
            conv = _round_int(totals["conversions"] * w) if has_conv else 0
            conv_value = round(totals["conversion_value"] * w, 2) if has_conv else 0.0
            rows.append({
                "platform": platform,
                "age_group": age,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "conversions": conv,
                "conversion_value": conv_value,
            })
    return pd.DataFrame(rows, columns=list(AGE_DEMO_COLUMNS))


def _validate_age_demographics(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == AGE_DEMO_COLUMNS
    assert set(df["age_group"].unique()) == set(AGE_BUCKETS)
    assert set(df["platform"].unique()) == {"Google Ads", "Meta Ads"}
    assert (df.loc[df["platform"] == "Meta Ads", "conversions"] == 0).all()
    assert (df.loc[df["platform"] == "Meta Ads", "conversion_value"] == 0.0).all()


def _build_gender_demographics(campaign_df: pd.DataFrame) -> pd.DataFrame:
    google_totals = campaign_df[campaign_df["platform"] == "google"][
        ["impressions", "clicks", "spend", "conversions", "conversion_value"]
    ].sum()
    meta_totals = campaign_df[campaign_df["platform"] == "meta"][
        ["impressions", "clicks", "spend"]
    ].sum()
    rows = []
    for platform, totals, has_conv in [
        ("Google Ads", google_totals, True),
        ("Meta Ads", meta_totals, False),
    ]:
        for gender, w in GENDER_WEIGHTS.items():
            impressions = _round_int(totals["impressions"] * w)
            clicks = _round_int(totals["clicks"] * w)
            spend = round(totals["spend"] * w, 2)
            conv = _round_int(totals["conversions"] * w) if has_conv else 0
            conv_value = round(totals["conversion_value"] * w, 2) if has_conv else 0.0
            cpc_val = spend / clicks if clicks else 0.0
            ctr_val = (clicks / impressions * 100) if impressions else 0.0
            rows.append({
                "platform": platform,
                "gender": gender,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "conversions": conv,
                "conversion_value": conv_value,
                "cpc": round(cpc_val, 2),
                "ctr": round(ctr_val, 2),
            })
    return pd.DataFrame(rows, columns=list(GENDER_DEMO_COLUMNS))


def _validate_gender_demographics(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == GENDER_DEMO_COLUMNS
    assert set(df["gender"].unique()) == {"female", "male"}
    assert len(df) == 4  # 2 platforms × 2 genders


def _build_device_demographics(campaign_df: pd.DataFrame) -> pd.DataFrame:
    google_totals = campaign_df[campaign_df["platform"] == "google"][
        ["impressions", "clicks", "spend", "conversions", "conversion_value"]
    ].sum()
    meta_totals = campaign_df[campaign_df["platform"] == "meta"][
        ["impressions", "clicks", "spend"]
    ].sum()
    rows = []
    for platform, totals, has_conv in [
        ("Google Ads", google_totals, True),
        ("Meta Ads", meta_totals, False),
    ]:
        for device, w in DEVICE_WEIGHTS.items():
            impressions = _round_int(totals["impressions"] * w)
            clicks = _round_int(totals["clicks"] * w)
            spend = round(totals["spend"] * w, 2)
            conv = _round_int(totals["conversions"] * w) if has_conv else 0
            conv_value = round(totals["conversion_value"] * w, 2) if has_conv else 0.0
            rows.append({
                "platform": platform,
                "device": device,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "conversions": conv,
                "conversion_value": conv_value,
            })
    return pd.DataFrame(rows, columns=list(DEVICE_DEMO_COLUMNS))


def _validate_device_demographics(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == DEVICE_DEMO_COLUMNS
    assert set(df["device"].unique()) == set(DEVICE_WEIGHTS)
    assert len(df) == 8  # 2 platforms × 4 devices


def _build_platform_placement(campaign_df: pd.DataFrame) -> pd.DataFrame:
    """Meta Ads only — publisher_platform × platform_position aggregates."""
    meta_totals = campaign_df[campaign_df["platform"] == "meta"][
        ["impressions", "clicks", "spend"]
    ].sum()
    n_combos = len(META_PUBLISHER_PLATFORMS) * len(META_PLATFORM_POSITIONS)
    per_combo_share = 1.0 / n_combos
    rows = []
    for pub in META_PUBLISHER_PLATFORMS:
        for pos in META_PLATFORM_POSITIONS:
            impressions = _round_int(meta_totals["impressions"] * per_combo_share)
            clicks = _round_int(meta_totals["clicks"] * per_combo_share)
            spend = round(meta_totals["spend"] * per_combo_share, 2)
            reach = _round_int(impressions * 0.85)
            cpc_val = spend / clicks if clicks else 0.0
            ctr_val = (clicks / impressions * 100) if impressions else 0.0
            rows.append({
                "publisher_platform": pub,
                "platform_position": pos,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "reach": reach,
                "cpc": round(cpc_val, 2),
                "ctr": round(ctr_val, 2),
            })
    return pd.DataFrame(rows, columns=list(PLATFORM_PLACEMENT_COLUMNS))


def _validate_platform_placement(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == PLATFORM_PLACEMENT_COLUMNS
    assert set(df["publisher_platform"].unique()) == set(META_PUBLISHER_PLATFORMS)


def _build_google_ads_network(campaign_df: pd.DataFrame) -> pd.DataFrame:
    google_totals = campaign_df[campaign_df["platform"] == "google"][
        ["impressions", "clicks", "spend", "conversions", "conversion_value"]
    ].sum()
    rows = []
    for network, w in GOOGLE_NETWORK_SPLIT.items():
        impressions = _round_int(google_totals["impressions"] * w)
        clicks = _round_int(google_totals["clicks"] * w)
        spend = round(google_totals["spend"] * w, 2)
        conv = _round_int(google_totals["conversions"] * w)
        conv_value = round(google_totals["conversion_value"] * w, 2)
        cpc_val = spend / clicks if clicks else 0.0
        ctr_val = (clicks / impressions * 100) if impressions else 0.0
        cpa_val = spend / conv if conv else 0.0
        rows.append({
            "network": network,
            "impressions": impressions,
            "clicks": clicks,
            "spend": spend,
            "conversions": conv,
            "conversion_value": conv_value,
            "cpc": round(cpc_val, 2),
            "ctr": round(ctr_val, 2),
            "cpa": round(cpa_val, 2),
        })
    return pd.DataFrame(rows, columns=list(GADS_NETWORK_COLUMNS))


def _validate_google_ads_network(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == GADS_NETWORK_COLUMNS
    assert set(df["network"].unique()) == set(GOOGLE_NETWORK_SPLIT)


def _build_google_ads_campaign_network(campaign_df: pd.DataFrame) -> pd.DataFrame:
    """Per-campaign network totals (Google only). Only Search/Display per campaign."""
    google = campaign_df[campaign_df["platform"] == "google"].copy()
    # Each Google campaign has a single network assigned at definition time.
    network_by_name = {name: net for name, net in GOOGLE_CAMPAIGNS}
    google["network"] = google["campaign_name"].map(network_by_name)
    grouped = google.groupby(["campaign_name", "network"]).agg(
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        spend=("spend", "sum"),
        conversions=("conversions", "sum"),
    ).reset_index()
    grouped = grouped[grouped["spend"] > 1.0]
    grouped["ctr"] = (grouped["clicks"] / grouped["impressions"] * 100).round(2)
    grouped["cpa"] = grouped.apply(
        lambda r: round(r["spend"] / r["conversions"], 2) if r["conversions"] else 0.0,
        axis=1,
    )
    return grouped[list(GADS_CAMPAIGN_NETWORK_COLUMNS)].reset_index(drop=True)


def _validate_google_ads_campaign_network(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == GADS_CAMPAIGN_NETWORK_COLUMNS
    assert (df["spend"] > 1.0).all()


def _build_google_ads_search_position(campaign_df: pd.DataFrame) -> pd.DataFrame:
    """Slot distribution within Google Search campaigns."""
    search_totals = campaign_df[
        (campaign_df["platform"] == "google")
        & (campaign_df["campaign_name"].isin(
            n for n, obj in GOOGLE_CAMPAIGNS if obj == "SEARCH"
        ))
    ][["impressions", "clicks", "spend", "conversions"]].sum()
    rows = []
    for slot, w in GOOGLE_SEARCH_SLOTS.items():
        impressions = _round_int(search_totals["impressions"] * w)
        clicks = _round_int(search_totals["clicks"] * w)
        spend = round(search_totals["spend"] * w, 2)
        conv = _round_int(search_totals["conversions"] * w)
        ctr_val = (clicks / impressions * 100) if impressions else 0.0
        cpa_val = spend / conv if conv else 0.0
        rows.append({
            "slot": slot,
            "impressions": impressions,
            "clicks": clicks,
            "spend": spend,
            "conversions": conv,
            "ctr": round(ctr_val, 2),
            "cpa": round(cpa_val, 2),
        })
    return pd.DataFrame(rows, columns=list(GADS_SEARCH_POSITION_COLUMNS))


def _validate_google_ads_search_position(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == GADS_SEARCH_POSITION_COLUMNS
    assert set(df["slot"].unique()) == set(GOOGLE_SEARCH_SLOTS)


# ---------------------------------------------------------------------------
# GA4 + Search Console fixtures
# ---------------------------------------------------------------------------

def _build_ga4_traffic(
    start: date,
    end: date,
    rng: np.random.Generator,
) -> pd.DataFrame:
    rows = []
    for day in _date_range(start, end):
        lift = _weekend_lift(day)
        for source, medium, channel in GA4_SOURCE_MEDIUM:
            jitter = 1.0 + (rng.random() - 0.5) * 0.20
            sessions = _round_int(GA4_BASELINE_SESSIONS * lift * jitter)
            users = _round_int(sessions * 0.85)
            new_users = _round_int(users * 0.4)
            engaged = _round_int(sessions * GA4_ENGAGEMENT_RATE)
            pageviews = sessions * GA4_PAGES_PER_SESSION
            rows.append({
                "date": day.isoformat(),
                "session_source": source,
                "session_medium": medium,
                "session_default_channel_group": channel,
                "sessions": sessions,
                "total_users": users,
                "new_users": new_users,
                "engaged_sessions": engaged,
                "engagement_rate": round(GA4_ENGAGEMENT_RATE, 4),
                "screen_page_views": pageviews,
                "average_session_duration": GA4_AVG_SESSION_DURATION,
            })
    return pd.DataFrame(rows, columns=list(GA4_TRAFFIC_COLUMNS))


def _validate_ga4_traffic(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == GA4_TRAFFIC_COLUMNS
    assert df["sessions"].min() > 0
    assert (df["engaged_sessions"] <= df["sessions"]).all()


def _build_search_console_queries(
    start: date,
    end: date,
    rng: np.random.Generator,
) -> pd.DataFrame:
    rows = []
    for day in _date_range(start, end):
        for i, query in enumerate(SC_QUERY_TERMS):
            # Stylized per-query impression curve (decay by index).
            base_imp = 200 - i * 15  # 200, 185, 170, ...
            impressions = max(_round_int(base_imp * (1.0 + (rng.random() - 0.5) * 0.30)), 1)
            ctr_val = 0.05 + i * 0.005  # 5% at top, decays/increases slightly
            clicks = _round_int(impressions * ctr_val)
            avg_position = round(1.5 + i * 0.5, 1)  # 1.5, 2.0, 2.5, ...
            actual_ctr = clicks / impressions if impressions else 0.0
            rows.append({
                "data_date": day.isoformat(),
                "query": query,
                "clicks": clicks,
                "impressions": impressions,
                "avg_position": avg_position,
                "ctr": round(actual_ctr, 4),
            })
    return pd.DataFrame(rows, columns=list(SC_QUERIES_COLUMNS))


def _validate_search_console_queries(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == SC_QUERIES_COLUMNS
    assert set(df["query"].unique()) == set(SC_QUERY_TERMS)


def _build_search_console_pages(
    start: date,
    end: date,
    rng: np.random.Generator,
) -> pd.DataFrame:
    rows = []
    for day in _date_range(start, end):
        for i, url in enumerate(SC_PAGES):
            base_imp = 300 - i * 25
            impressions = max(_round_int(base_imp * (1.0 + (rng.random() - 0.5) * 0.30)), 1)
            ctr_val = 0.04 + i * 0.003
            clicks = _round_int(impressions * ctr_val)
            avg_position = round(2.0 + i * 0.4, 1)
            rows.append({
                "data_date": day.isoformat(),
                "url": url,
                "clicks": clicks,
                "impressions": impressions,
                "avg_position": avg_position,
            })
    return pd.DataFrame(rows, columns=list(SC_PAGES_COLUMNS))


def _validate_search_console_pages(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == SC_PAGES_COLUMNS
    assert set(df["url"].unique()) == set(SC_PAGES)


def _build_daily_marketing_summary(
    campaign_df: pd.DataFrame,
    ga4_df: pd.DataFrame,
    sc_df: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate per-day across sources. Derived from per-source fixtures."""
    ads_daily = campaign_df.groupby(["date", "platform"]).agg(
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        spend=("spend", "sum"),
        conversions=("conversions", "sum"),
    ).reset_index()
    ga4_daily = ga4_df.groupby("date").agg(sessions=("sessions", "sum")).reset_index()
    sc_daily = sc_df.groupby("data_date").agg(
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
    ).reset_index().rename(columns={"data_date": "date"})

    rows = []
    for _, r in ads_daily.iterrows():
        source = "google_ads" if r["platform"] == "google" else "meta_ads"
        rows.append({
            "date": r["date"],
            "source": source,
            "impressions": int(r["impressions"]),
            "clicks": int(r["clicks"]),
            "spend": float(r["spend"]),
            "sessions": None,
            "conversions": int(r["conversions"]),
        })
    for _, r in ga4_daily.iterrows():
        rows.append({
            "date": r["date"],
            "source": "ga4",
            "impressions": None,
            "clicks": None,
            "spend": None,
            "sessions": int(r["sessions"]),
            "conversions": None,
        })
    for _, r in sc_daily.iterrows():
        rows.append({
            "date": r["date"],
            "source": "search_console",
            "impressions": int(r["impressions"]),
            "clicks": int(r["clicks"]),
            "spend": None,
            "sessions": None,
            "conversions": None,
        })
    return pd.DataFrame(rows, columns=list(DAILY_SUMMARY_COLUMNS)).sort_values(
        ["date", "source"]
    ).reset_index(drop=True)


def _validate_daily_marketing_summary(df: pd.DataFrame) -> None:
    assert tuple(df.columns) == DAILY_SUMMARY_COLUMNS
    assert set(df["source"].unique()) == {"google_ads", "meta_ads", "ga4", "search_console"}
    # Row count: 4 sources × number of days in the window.
    n_days = df["date"].nunique()
    assert len(df) == n_days * 4, (
        f"expected {n_days * 4} rows ({n_days} days × 4 sources), got {len(df)}"
    )
    # Null patterns per source.
    ga4_rows = df[df["source"] == "ga4"]
    assert ga4_rows["sessions"].notna().all(), "ga4 rows missing sessions"
    assert ga4_rows["spend"].isna().all(), "ga4 rows should have null spend"
    sc_rows = df[df["source"] == "search_console"]
    assert sc_rows["impressions"].notna().all(), "search_console rows missing impressions"
    assert sc_rows["spend"].isna().all(), "search_console rows should have null spend"
    assert sc_rows["sessions"].isna().all(), "search_console rows should have null sessions"


def _resolve_window(today: date | None = None) -> tuple[date, date]:
    """Most-recent 12 calendar months ending yesterday."""
    today = today or date.today()
    end = today - timedelta(days=1)
    start = end - timedelta(days=365)
    return start, end


def _write(out_dir: Path, name: str, df: pd.DataFrame) -> None:
    path = out_dir / name
    df.to_csv(path, index=False)
    print(f"Wrote {path}: {len(df):,} rows, {len(df.columns)} columns")


def main(out_dir: Path) -> None:
    # Locale is en_US so synthetic customer names don't accidentally embed
    # tokens that look like the live build's account labels.
    faker = Faker("en_US")
    Faker.seed(FAKER_SEED)
    faker.seed_instance(FAKER_SEED)
    rng = np.random.default_rng(RNG_SEED)

    start, end = _resolve_window()
    print(f"Window: {start} -> {end} ({(end - start).days + 1} days)")
    out_dir.mkdir(parents=True, exist_ok=True)

    bookings = _build_bookings(start, end, faker, rng)
    _validate_bookings(bookings)
    _write(out_dir, "bookings.csv", bookings)

    campaign = _build_campaign_performance(start, end, rng)
    _validate_campaign_performance(campaign)
    _write(out_dir, "campaign_performance.csv", campaign)

    loc = _build_location_performance(bookings, campaign, do_filter=False)
    _validate_location_performance(loc, "location_performance")
    _write(out_dir, "location_performance.csv", loc)

    loc_do = _build_location_performance(bookings, campaign, do_filter=True)
    _validate_location_performance(loc_do, "location_performance_do")
    _write(out_dir, "location_performance_do.csv", loc_do)

    age_demo = _build_age_demographics(campaign, rng)
    _validate_age_demographics(age_demo)
    _write(out_dir, "age_demographics.csv", age_demo)

    gender_demo = _build_gender_demographics(campaign)
    _validate_gender_demographics(gender_demo)
    _write(out_dir, "gender_demographics.csv", gender_demo)

    device_demo = _build_device_demographics(campaign)
    _validate_device_demographics(device_demo)
    _write(out_dir, "device_demographics.csv", device_demo)

    placement = _build_platform_placement(campaign)
    _validate_platform_placement(placement)
    _write(out_dir, "platform_placement.csv", placement)

    gads_net = _build_google_ads_network(campaign)
    _validate_google_ads_network(gads_net)
    _write(out_dir, "google_ads_network.csv", gads_net)

    gads_camp_net = _build_google_ads_campaign_network(campaign)
    _validate_google_ads_campaign_network(gads_camp_net)
    _write(out_dir, "google_ads_campaign_network.csv", gads_camp_net)

    gads_search = _build_google_ads_search_position(campaign)
    _validate_google_ads_search_position(gads_search)
    _write(out_dir, "google_ads_search_position.csv", gads_search)

    ga4 = _build_ga4_traffic(start, end, rng)
    _validate_ga4_traffic(ga4)
    _write(out_dir, "ga4_traffic.csv", ga4)

    sc_queries = _build_search_console_queries(start, end, rng)
    _validate_search_console_queries(sc_queries)
    _write(out_dir, "search_console_queries.csv", sc_queries)

    sc_pages = _build_search_console_pages(start, end, rng)
    _validate_search_console_pages(sc_pages)
    _write(out_dir, "search_console_pages.csv", sc_pages)

    daily = _build_daily_marketing_summary(campaign, ga4, sc_queries)
    _validate_daily_marketing_summary(daily)
    _write(out_dir, "daily_marketing_summary.csv", daily)

    # Cross-fixture sanity: total campaign conversions must not exceed total
    # non-canceled bookings — plan Step 3.3 "no impossible attribution".
    total_conversions = int(campaign["conversions"].sum())
    non_canceled_bookings = int((bookings["status"] != "canceled").sum())
    assert total_conversions <= non_canceled_bookings, (
        f"impossible attribution: {total_conversions} campaign conversions exceed "
        f"{non_canceled_bookings} non-canceled bookings — tune CVR down."
    )
    print(
        f"Cross-fixture check OK: {total_conversions} conversions vs "
        f"{non_canceled_bookings} non-canceled bookings."
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate demo CSV fixtures.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("demo_data"),
        help="Output directory for the CSVs (default: demo_data/).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(args.out)
