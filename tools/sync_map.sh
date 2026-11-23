#!/usr/bin/env bash
# Copy leakhunt's canonical detection map into app/ and ultra/ (leakhunt is private, so CI only checks the two copies match).
set -euo pipefail
SRC="${1:-$HOME/leakhunt/src/leakhunt/data/bruqi_detection_map.json}"
cd "$(dirname "$0")/.."
for d in app ultra; do cp "$SRC" "$d/bruqi_detection_map.json"; done
python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))),"domains")' app/bruqi_detection_map.json
