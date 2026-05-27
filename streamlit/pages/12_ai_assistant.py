"""Northern Sauna AI — Natural-language Q&A (live-build-only stub).

In the live build this page is a chat interface that turns plain-English
business questions into safe BigQuery and returns a chart or table —
plus a Copy Bot that drafts ad copy from a knowledge base. The public
demo can't run it because it requires an Anthropic API key wired to the
real schema. See `components/live_build_stub.py` for the shared layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from components.live_build_stub import render_live_build_stub  # noqa: E402
from utils import render_sidebar_nav  # noqa: E402

st.set_page_config(
    page_title="Northern Sauna AI",
    page_icon=":material/auto_awesome:",
    layout="wide",
)

if not st.session_state.get("authenticated", False):
    st.switch_page("app.py")

st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

render_sidebar_nav("Northern Sauna AI")

render_demo_banner()

render_live_build_stub(
    title="Northern Sauna AI",
    description_paragraphs=[
        "**In the live build:** Northern Sauna AI is two tools in one chat surface. "
        "The first turns plain-English questions (\"how did Saturday "
        "compare to last week?\", \"which locations underperformed in "
        "April?\") into safe, partition-filtered BigQuery and returns a "
        "chart, KPI, or table. The second — Copy Bot — drafts on-brand ad "
        "copy from a curated knowledge base of past creative, tone of "
        "voice, and offer mechanics.",
        "**How the SQL side stays safe:** every generated query goes "
        "through a catalog-driven safety validator that whitelists "
        "tables, blocks unbounded scans on partitioned data, and caps "
        "byte-billed. The catalog (`schema_catalog.yaml`) is the single "
        "source of truth for which tables / columns / partition keys the "
        "model is allowed to see — drift between the catalog and the "
        "warehouse fails an audit job daily.",
        "**Data sources:** the full BigQuery warehouse the rest of the "
        "dashboard reads from (Bookeo, Google Ads, Meta Ads, GA4, Search "
        "Console). Provider is Claude via the Anthropic API.",
    ],
    why_not_live=(
        "The natural-language SQL surface needs an Anthropic API key "
        "configured against the real warehouse schema. Wiring that into "
        "a public demo would mean either shipping a key (unsafe) or "
        "shipping a mock that drifts from how the real thing behaves "
        "(misleading). The About page on this app describes the "
        "architecture in more depth — see \"About Northern Sauna AI\"."
    ),
)

render_footer()
