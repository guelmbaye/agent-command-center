#!/usr/bin/env bash
# Deroule la demo hero contre une instance ACC en fonctionnement.
# Usage : ACC_URL=http://localhost:8080 ./scripts/demo_walkthrough.sh
set -euo pipefail

ACC="${ACC_URL:-http://localhost:8080}"
KEY_HEADER=()
[[ -n "${ACC_API_KEY:-}" ]] && KEY_HEADER=(-H "x-api-key: ${ACC_API_KEY}")

api() { curl -sS "${KEY_HEADER[@]}" -H 'Content-Type: application/json' "$@"; }

echo "▸ Reinitialisation de l'etat de demo"
api -X POST "${ACC}/api/v1/demo/reset" > /dev/null

echo "▸ Armement de la panne fournisseur (deterministe)"
api -X POST "${ACC}/api/v1/demo/fail/supplier-a"

echo "▸ Creation de la mission"
MISSION=$(api -X POST "${ACC}/api/v1/missions" \
  -d '{"objective":"Protect production schedule"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["mission_id"])')
echo "  mission = ${MISSION}"

sleep 3
echo "▸ Etat de mission"
api "${ACC}/api/v1/missions/${MISSION}/state" | python3 -m json.tool

echo "▸ Options de recovery evaluees"
api "${ACC}/api/v1/missions/${MISSION}/evidence" | python3 -m json.tool

echo "▸ Approbations en attente"
APPROVAL=$(api "${ACC}/api/v1/approvals?status=PENDING" \
  | python3 -c 'import sys,json;a=[x for x in json.load(sys.stdin)["approvals"] if x["action"]=="purchase.execute"];print(a[0]["approval_id"] if a else "")')
echo "  approbation = ${APPROVAL}"

echo "▸ Interruption du runtime puis reprise"
api -X POST "${ACC}/api/v1/demo/interrupt-agent?mission_id=${MISSION}"
api -X POST "${ACC}/api/v1/missions/${MISSION}/resume" -d '{}' | python3 -m json.tool

echo "▸ Decision humaine : approbation"
api -X POST "${ACC}/api/v1/approvals/${APPROVAL}/approve" \
  -d '{"decided_by":"operator","comment":"Continuite de production prioritaire"}' > /dev/null

sleep 3
echo "▸ Etat final et metriques"
api "${ACC}/api/v1/missions/${MISSION}/state" | python3 -m json.tool
api "${ACC}/api/v1/metrics" | python3 -m json.tool
