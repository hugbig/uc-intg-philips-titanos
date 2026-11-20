#!/usr/bin/env bash
# Register the dev driver with the Remote simulator (Core-API REST), without mDNS.
# Doc: https://github.com/unfoldedcircle/core-api/blob/main/doc/integration-driver/driver-registration.md
# Usage: scripts/register_dev_driver.sh   (simulator on localhost:8080, web-configurator PIN 1234)
set -euo pipefail

CORE_URL="${CORE_URL:-http://localhost:8080}"
CORE_AUTH="${CORE_AUTH:-web-configurator:1234}"
DRIVER_ID="philips_titanos_ambilight"
DRIVER_URL="${DRIVER_URL:-ws://${DEV_SUBNET_PREFIX:-172.28.0}.20:9090}"
# Body built from driver.json (name, version, setup schema...) + the dev driver URL.
build_body() {
  DRIVER_URL="$DRIVER_URL" python3 - <<'PY'
import json, os
manifest = json.load(open("driver.json"))
keys = ("driver_id", "name", "version", "description", "developer", "home_page", "release_date",
        "setup_data_schema", "device_discovery")
body = {key: manifest[key] for key in keys if key in manifest}
body["name"] = {lang: f"{text} (dev)" for lang, text in manifest["name"].items()}
body.update(driver_url=os.environ["DRIVER_URL"], enabled=True)
print(json.dumps(body))
PY
}

api() { curl -sS --fail-with-body -u "$CORE_AUTH" -H "Content-Type: application/json" "$@"; }

if api -o /dev/null "$CORE_URL/api/intg/drivers/$DRIVER_ID" 2>/dev/null; then
  echo "Driver $DRIVER_ID already registered: deleting it"
  api -X DELETE "$CORE_URL/api/intg/drivers/$DRIVER_ID" >/dev/null
fi

build_body | api -X POST "$CORE_URL/api/intg/drivers" -d @-
echo
echo "Driver $DRIVER_ID registered ($DRIVER_URL)."

echo "Physical buttons of the simulated model (GET /api/cfg/device/button_layout) :"
api "$CORE_URL/api/cfg/device/button_layout" || echo "(endpoint unavailable)"
echo
