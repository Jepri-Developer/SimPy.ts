#!/usr/bin/env bash
# Smoke test end-to-end: buat project baru, build, jalankan server, lalu uji lewat HTTP.
# Prasyarat: `pip install -e .` (perintah `simpy` tersedia), Node >= 22.18, npm, curl.
set -euo pipefail

PORT="${SMOKE_PORT:-8765}"
BASE="http://127.0.0.1:${PORT}"
WORK="$(mktemp -d)"
PID=""

cleanup() {
  if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

fail() { echo "SMOKE GAGAL: $1" >&2; [ -f "$WORK/smoke-app/server.log" ] && tail -n 30 "$WORK/smoke-app/server.log" >&2; exit 1; }

cd "$WORK"
simpy create smoke-app
cd smoke-app
npm install --no-audit --no-fund
cp .env.example .env

simpy build
[ -f dist/app.js ] || fail "dist/app.js tidak dibuat"
[ -f dist/index.html ] || fail "dist/index.html tidak dibuat"
[ -f .simpy/api.ts ] || fail ".simpy/api.ts tidak dibuat"

SIMPY_PORT="$PORT" simpy dev --no-reload >server.log 2>&1 &
PID=$!
for _ in $(seq 1 60); do
  curl -fsS "$BASE/api/hello" >/dev/null 2>&1 && break
  kill -0 "$PID" 2>/dev/null || fail "server berhenti sebelum siap"
  sleep 0.5
done

curl -fsS "$BASE/api/hello" | grep -q "Hello from smoke-app" || fail "/api/hello"
curl -fsS "$BASE/" | grep -q 'id="app"' || fail "halaman utama"
curl -fsS "$BASE/about" | grep -q 'id="app"' || fail "route sisi klien"
curl -fsS "$BASE/static/app.js" >/dev/null || fail "/static/app.js"

HEADERS="$(curl -fsS -D - -o /dev/null "$BASE/")"
echo "$HEADERS" | grep -qi "^content-security-policy:" || fail "CSP tidak ada"
echo "$HEADERS" | grep -qi "^x-content-type-options: nosniff" || fail "nosniff tidak ada"

CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/greet" \
  -H 'Content-Type: application/json' -d '{"name":"Ani"}')"
[ "$CODE" = "403" ] || fail "POST tanpa token CSRF seharusnya 403, dapat $CODE"

JAR="$WORK/cookies.txt"
curl -fsS -c "$JAR" "$BASE/api/hello" >/dev/null
TOKEN="$(awk '$6 == "simpy_csrf" {print $7}' "$JAR")"
[ -n "$TOKEN" ] || fail "cookie CSRF tidak dipasang"
curl -fsS -b "$JAR" -H "X-CSRF-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Ani"}' "$BASE/api/greet" | grep -q "Halo, Ani!" || fail "POST dengan token"

CODE="$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -H "X-CSRF-Token: $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":""}' "$BASE/api/greet")"
[ "$CODE" = "422" ] || fail "validasi seharusnya 422, dapat $CODE"

CODE="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/me")"
[ "$CODE" = "401" ] || fail "/api/me tanpa login seharusnya 401, dapat $CODE"

echo "SMOKE OK"
