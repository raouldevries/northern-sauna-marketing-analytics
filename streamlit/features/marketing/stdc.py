"""STDC phase classification for marketing campaigns."""

import pandas as pd

from features.marketing.constants import STDC_SUGGESTIONS


def suggest_stdc_phase(campaign_name):
    """Suggest STDC phase based on campaign name keywords."""
    if pd.isna(campaign_name) or not isinstance(campaign_name, str):
        return 'Untagged'
    name_lower = campaign_name.lower()

    # Check phases in priority order: DO → SEE → THINK → CARE
    for phase in ('DO', 'SEE', 'THINK', 'CARE'):
        for keyword in STDC_SUGGESTIONS[phase]:
            if keyword in name_lower:
                return phase

    return 'Untagged'
