#!/bin/bash
# test_local.sh
# Test the broker locally without a real GitHub Actions run.
# Requires: a real GITHUB_TOKEN from an active run, OR use mock mode below.

BROKER_URL="http://localhost:8080"

echo "=== Health Check ==="
curl -s "$BROKER_URL/health" | jq .

echo ""
echo "=== Test 1: No token (should 401) ==="
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST "$BROKER_URL/auth" \
  -H "Content-Type: application/json" \
  -d '{"namespace":"namespace1","run_id":"123","repo":"myorg/github-abc"}'

echo ""
echo "=== Test 2: PAT token rejected (should 401) ==="
curl -s -X POST "$BROKER_URL/auth" \
  -H "Authorization: Bearer ghp_fakepersonaltoken" \
  -H "Content-Type: application/json" \
  -d '{"namespace":"namespace1","run_id":"123","repo":"myorg/github-abc"}' | jq .

echo ""
echo "=== Test 3: Fine-grained PAT rejected (should 401) ==="
curl -s -X POST "$BROKER_URL/auth" \
  -H "Authorization: Bearer github_pat_faketoken" \
  -H "Content-Type: application/json" \
  -d '{"namespace":"namespace1","run_id":"123","repo":"myorg/github-abc"}' | jq .

echo ""
echo "=== Test 4: Real ghs_ token (replace with actual token from a run) ==="
# To get a real ghs_ token:
# 1. Add a step in any GitHub Actions workflow:
#    - run: echo "TOKEN=${{ secrets.GITHUB_TOKEN }}" — note: will be masked
#    Instead do:
#    - run: echo ${{ toJSON(secrets.GITHUB_TOKEN) }} > /tmp/t.txt
# Or use the GitHub CLI: gh run view --log
#
# Then run:
# REAL_TOKEN="ghs_xxxx"
# curl -s -X POST "$BROKER_URL/auth" \
#   -H "Authorization: Bearer $REAL_TOKEN" \
#   -H "Content-Type: application/json" \
#   -d '{"namespace":"namespace1","run_id":"<real_run_id>","repo":"myorg/github-abc"}' | jq .

echo "(skipped — replace with real token)"
