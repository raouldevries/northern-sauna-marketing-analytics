"""Marketing constants: STDC phase colors and suggestions.

Location-name mapping and keyword tables were removed when the marketing
module migrated to `v_location_performance` — concept-based weighted
allocation lives in the view; the page reads pre-allocated rows.
"""

# STDC phase colors
STDC_COLORS = {
    'SEE': '#3498db',      # Blue
    'THINK': '#f39c12',    # Orange
    'DO': '#27ae60',       # Green
    'CARE': '#9b59b6',     # Purple
    'Untagged': '#9ca3af'  # Gray
}

# Default STDC suggestions based on campaign keywords
# Google Ads naming: NL | S | ... (Search), NL | PM | ... (Performance Max)
# Meta naming: Clicks | ..., Reach - ..., Conversions | ...
STDC_SUGGESTIONS = {
    'SEE': ['display', 'demand gen', 'reach', 'awareness', 'see'],
    'THINK': ['non-branded', 'non branded', 'think', 'consideration', 'clicks |'],
    'DO': ['| s |', '| pm |', 'branded', 'brand', 'conversions', 'conversion', 'do', 'purchase', 'retargeting', 'rm', 'remarketing'],
    'CARE': ['care', 'loyalty', 'retention', 'membership']
}
