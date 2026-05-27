"""Northern Sauna Analytics — Reviews (live-build-only stub).

In the live build this page renders Google Business Profile reviews and
turns them into operational signals. The public demo can't run it
because review text is real customer language and creative themes need
authentic ad copy. See `components/live_build_stub.py` for the shared
layout.
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
    page_title="Northern Sauna - Reviews",
    page_icon=":material/reviews:",
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

render_sidebar_nav("Reviews")

render_demo_banner()

render_live_build_stub(
    title="Reviews",
    description_paragraphs=[
        "**In the live build:** the Reviews page ingests Google Business "
        "Profile reviews across every location via the GBP API, tagging "
        "each review with a star rating, language, and a customer-language "
        "theme (water/view, sauna ritual, staff, value, cleanliness, "
        "booking flow). The page shows per-location reputation, "
        "response-rate tracking, and a trending-themes feed.",
        "**Why it's on the dashboard:** review themes drive the ad-copy "
        "matching workflow on the Northern Sauna AI page — when reviewers "
        "consistently mention \"the waterfront view\" or \"the cold "
        "plunge,\" creative production gets a steady signal of which "
        "angles resonate. Marketing and ops use the same page: ops to "
        "respond to negative reviews quickly, marketing to surface what "
        "language is already converting.",
        "**Data sources:** Google Business Profile API (live-only), "
        "ad-copy themes joined from Meta / Google ad creative tables.",
    ],
    why_not_live=(
        "Review text is real customer language across multiple real "
        "locations. Synthesising it without leaking real venue identity "
        "or risking AI-generated text that resembles real reviewers "
        "wasn't a tradeoff worth making for a portfolio demo. The "
        "ad-copy theme join also depends on authentic creative — the "
        "creative-text sync is the focus of a separate live integration "
        "(see the Northern Sauna AI page)."
    ),
)

render_footer()
