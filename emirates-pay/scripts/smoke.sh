#!/bin/sh
# End-to-end smoke test. Usage: sh scripts/smoke.sh [base_url]
# Exits non-zero on the first failure, so it can gate a CI job or a post-deploy check.
set -eu
BASE="${1:-http://localhost:8080}"
RUN="$(date +%s)$$"

need() { command -v "$1" >/dev/null || { echo "missing tool: $1"; exit 2; }; }
need curl; need python3

json() { python3 -c "import sys,json; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1"; }
check() { if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1 (expected '$3', got '$2')"; exit 1; fi; }

check "health"  "$(curl -fsS "$BASE/health" | json "d['status']")" "ok"
check "ready"   "$(curl -fsS "$BASE/ready"  | json "d['status']")" "ready"

A=$(curl -fsS -X POST "$BASE/api/auth/uaepass-mock" -H 'Content-Type: application/json' \
      -d "{\"name\":\"Alice\",\"email\":\"alice$RUN@example.ae\"}")
B=$(curl -fsS -X POST "$BASE/api/auth/uaepass-mock" -H 'Content-Type: application/json' \
      -d "{\"name\":\"Bob\",\"email\":\"bob$RUN@example.ae\"}")
TA=$(echo "$A" | json "d['token']");  TB=$(echo "$B" | json "d['token']")
WB=$(echo "$B" | json "d['wallet']['wallet_no']")
echo "PASS  two wallets created (Bob = $WB)"

curl -fsS -X POST "$BASE/api/wallet/topup" -H "Authorization: Bearer $TA" \
  -H 'Content-Type: application/json' -d '{"amount":"500"}' >/dev/null
KEY="smoke-$RUN"
for i in 1 2; do   # second call is a deliberate retry with the same Idempotency-Key
  curl -fsS -X POST "$BASE/api/transfer" -H "Authorization: Bearer $TA" -H "Idempotency-Key: $KEY" \
    -H 'Content-Type: application/json' -d "{\"to_wallet\":\"$WB\",\"amount\":\"100\"}" >/dev/null
done
check "sender balance (500 - 100 - 1.00 fee - 0.05 VAT, charged once)" \
  "$(curl -fsS "$BASE/api/me" -H "Authorization: Bearer $TA" | json "d['wallet']['balance']")" "398.95"
check "receiver balance" \
  "$(curl -fsS "$BASE/api/me" -H "Authorization: Bearer $TB" | json "d['wallet']['balance']")" "100.00"
check "unauthenticated request rejected" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/me")" "401"
curl -fsS "$BASE/metrics" | grep -q '^http_requests_total' && echo "PASS  /metrics exposes http_requests_total"
echo "All smoke checks passed."
