#!/usr/bin/env bash
# Smoke-test one Abolita origin. Usage: deploy/smoke.sh [BASE_URL] [https-host ...]
#   BASE_URL default http://127.0.0.1:8081 (the VPS host port). Each https-host gets /healthz + / checked.
# Read-only GETs/HEADs only (no scans). Exit 1 if any check fails.
set -u
B="${1:-http://127.0.0.1:8081}"; shift || true
fail=0
ok() { printf 'ok    %s\n' "$1"; }
bad() { printf 'FAIL  %s\n' "$1"; fail=1; }
# check NAME URL WANT_CODE(s, a|b) [GREP | !MUST_BE_ABSENT] [extra curl args...]
check() {
  local name="$1" url="$2" want="$3" pat="${4:-}"; shift 4 2>/dev/null || shift $#
  local body code
  body="$(mktemp)"
  code="$(curl -s --max-time 15 -o "$body" -w '%{http_code}' "$@" "$url")"
  case "|$want|" in
    *"|$code|"*)
      if [ "${pat#!}" != "$pat" ] && grep -q -- "${pat#!}" "$body"; then bad "$name: $url -> $code but has \"${pat#!}\""
      elif [ -n "$pat" ] && [ "${pat#!}" = "$pat" ] && ! grep -q -- "$pat" "$body"; then bad "$name: $url -> $code but no \"$pat\""
      else ok "$name: $code${pat:+ (\"$pat\")}"; fi ;;
    *) bad "$name: $url -> $code (want $want)" ;;
  esac
  rm -f "$body"
}
check healthz        "$B/healthz"                         200 '"ok": true'
check landing        "$B/"                                200 'Abolita'
check landing-is-site "$B/"                               200 '!id="app-config"'
check scan-page      "$B/scan/"                           200 'Free leak scan'
check legacy-ui      "$B/app/"                            200 'Find Your Leaks'
check legacy-js      "$B/static/app.js"                   200 'prefillFromUrl'
check api-404-json   "$B/api/scan-result/nonexistent"     404 '"error"'
check landing-h      "$B/?h=x"                            200 '!id="app-config"'
check trav-dotdot    "$B/../.env"                         "404|400" '' --path-as-is
check trav-encoded   "$B/..%2f.env"                       "404|400"
check trav-app       "$B/app/../public_app.py"            "404|400" '' --path-as-is
check trav-static    "$B/static/..%2f..%2fapp/db.py"      "404|400"
check dotfile        "$B/.env"                            "404|400"
for h in "$@"; do
  [ -n "$h" ] || continue
  check "https $h healthz" "https://$h/healthz" 200 '"ok": true' --retry 3 --retry-delay 5 --retry-all-errors
  check "https $h /"       "https://$h/"        200 'Abolita'   --retry 3 --retry-delay 5 --retry-all-errors
done
[ "$fail" = 0 ] && echo "SMOKE GREEN" || echo "SMOKE RED"
exit "$fail"
