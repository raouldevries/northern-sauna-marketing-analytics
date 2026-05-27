#!/usr/bin/env bash
# Grep gate for the demo repo. Fails (exit 1) if any banned identifier is present.
# Used by audit-loop validate_command and recommended for pre-push checks.

set -u
cd "$(git rev-parse --show-toplevel)" || exit 2

BANNED=(
  'kuuma'
  'Kuuma'
  'Bjork'
  'Bjørk'
  'Matsu'
  'Delfshaven'
  'Rijnhaven'
  'NYMA'
  'Marineterrein'
  "Aan 't IJ"
  'Sloterplas'
  'Voogges'
  'Scheveningen'
  'Katwijk'
  'Bloemendaal'
  'Wijk aan Zee'
  'Den Bosch'
  'Amsterdam'
  'Rotterdam'
  'Nijmegen'
  '484114'
  '412680851'
  'raoul@soulkitchen'
  'soulkitchen'
  'kuuma_data'
  'kuuma_monitoring'
)

INCLUDES=(
  --include='*.py'
  --include='*.sql'
  --include='*.yaml'
  --include='*.yml'
  --include='*.toml'
  --include='*.md'
  --include='*.json'
  --include='*.sh'
)

EXCLUDE_DIRS=(
  --exclude-dir='.git'
  --exclude-dir='.venv'
  --exclude-dir='__pycache__'
  --exclude-dir='node_modules'
  --exclude='validate_identifiers.sh'
  --exclude='progress.md'
)

fail=0
for token in "${BANNED[@]}"; do
  hits=$(grep -rn "$token" "${INCLUDES[@]}" "${EXCLUDE_DIRS[@]}" . 2>/dev/null || true)
  count=$(printf '%s\n' "$hits" | grep -c . || true)
  if [ "$count" -gt 0 ]; then
    echo "FAIL: '$token' has $count hits:"
    printf '%s\n' "$hits" | head -20
    echo ""
    fail=1
  else
    echo "OK:   '$token' has 0 hits"
  fi
done

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "Identifier scrub incomplete. Fix and re-run."
  exit 1
fi

# Sanity-check that bq_client.py centralizes the constants via os.environ.
BQ_CLIENT='streamlit/data/bq_client.py'
if [ -f "$BQ_CLIENT" ]; then
  for const in 'PROJECT_ID' 'GA4_PROPERTY_ID' 'DATASET'; do
    if ! grep -qE "^${const}\s*=\s*os\.environ\.get\(" "$BQ_CLIENT"; then
      echo "FAIL: ${BQ_CLIENT} is missing an os.environ.get-backed ${const} constant"
      fail=1
    fi
  done
fi

if [ "$fail" -ne 0 ]; then
  exit 1
fi

echo ""
echo "All identifier gates pass."
