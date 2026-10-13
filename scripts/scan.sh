#!/usr/bin/env bash
# Refresh site/data/wiki.json from storiesofmnm.com using the scanner.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
W="$(mktemp -d)"
mkdir -p "$W/data"
cp "$ROOT/scanner/mnm_companion.py" "$W/"
cp "$ROOT/site/curated.json" "$W/curated.json"
cp "$ROOT/site/data/wiki.json" "$W/data/snapshot.json"
echo '{"desktop_notifications": false}' > "$W/config.json"
echo '{"characters": []}' > "$W/data/user.json"
( cd "$W" && timeout 900 python3 mnm_companion.py scan )
cp "$W/data/snapshot.json" "$ROOT/site/data/wiki.json"
