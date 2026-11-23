import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_app_and_ultra_maps_match():
    app = json.loads((ROOT / "app/bruqi_detection_map.json").read_text())
    ultra = json.loads((ROOT / "ultra/bruqi_detection_map.json").read_text())
    assert app == ultra, "run tools/sync_map.sh"
    assert all("{name}" in (v.get("check_url") or "{name}") for v in app.values())
