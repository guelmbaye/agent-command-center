#!/usr/bin/env bash
# Suivi des coûts ACC — état de la dépense et des garde-fous.
#
# Usage :  PROJECT_ID=xxx ./scripts/costs.sh
#          PROJECT_ID=xxx BILLING_ACCOUNT=0X0X0X-0X0X0X-0X0X0X ./scripts/costs.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID est requis}"
REGION="${REGION:-europe-west1}"

blue()  { printf '\033[94m%s\033[0m\n' "$*"; }
green() { printf '  \033[92m✓\033[0m %s\n' "$*"; }
warn()  { printf '  \033[93m▲\033[0m %s\n' "$*"; }

blue "── Budget et alertes ──"
BILLING_ACCOUNT="${BILLING_ACCOUNT:-$(gcloud beta billing projects describe "${PROJECT_ID}" \
  --format='value(billingAccountName)' 2>/dev/null | sed 's|billingAccounts/||')}"

if [[ -z "${BILLING_ACCOUNT}" ]]; then
  warn "Aucun compte de facturation lié — le projet ne peut rien facturer (ni fonctionner)."
else
  green "Compte de facturation : ${BILLING_ACCOUNT}"
  if gcloud billing budgets list --billing-account="${BILLING_ACCOUNT}" \
       --format='table(displayName,amount.specifiedAmount.units)' 2>/dev/null | grep -q .; then
    gcloud billing budgets list --billing-account="${BILLING_ACCOUNT}" \
      --format='table(displayName,amount.specifiedAmount.units,thresholdRules.len())'
  else
    warn "AUCUN BUDGET DÉFINI. Créez-en un avant de laisser tourner quoi que ce soit :"
    echo "     gcloud billing budgets create \\"
    echo "       --billing-account=${BILLING_ACCOUNT} \\"
    echo "       --display-name='ACC hackathon' --budget-amount=50USD \\"
    echo "       --filter-projects='projects/${PROJECT_ID}' \\"
    echo "       --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 \\"
    echo "       --threshold-rule=percent=1.0"
  fi
fi

blue "── Garde-fous d'échelle (le vrai frein à la dépense) ──"
for svc in acc-api acc-web acc-mock-enterprise; do
  if gcloud run services describe "${svc}" --region="${REGION}" --project="${PROJECT_ID}" \
       --format='value(name)' >/dev/null 2>&1; then
    read -r MIN MAX <<< "$(gcloud run services describe "${svc}" --region="${REGION}" \
      --project="${PROJECT_ID}" \
      --format='value(spec.template.metadata.annotations."autoscaling.knative.dev/minScale",
                      spec.template.metadata.annotations."autoscaling.knative.dev/maxScale")' \
      2>/dev/null || echo "? ?")"
    green "${svc} : min=${MIN:-0} max=${MAX:-?}"
    [[ "${MIN:-0}" != "0" && -n "${MIN}" ]] && \
      warn "  min > 0 : ce service facture même au repos."
  else
    warn "${svc} : non déployé"
  fi
done

blue "── Volumétrie qui pilote la facture ──"
MISSIONS=$(gcloud firestore documents list --collection-ids=missions \
  --project="${PROJECT_ID}" --format='value(name)' 2>/dev/null | wc -l || echo "?")
echo "  missions persistées : ${MISSIONS}"
echo "  (chaque mission ≈ 60–90 écritures Firestore : events, audit, checkpoints)"

blue "── Rapports détaillés ──"
cat <<TXT
  Coût par service et par label :
    https://console.cloud.google.com/billing/${BILLING_ACCOUNT:-BILLING_ID}/reports?project=${PROJECT_ID}
    → Grouper par « Label » puis « app: acc » pour isoler ACC
    → Grouper par « SKU » pour voir la part Gemini / Model Armor

  Consommation de tokens Vertex AI :
    https://console.cloud.google.com/vertex-ai/quotas?project=${PROJECT_ID}

  Arrêt complet de la facturation :
    ./scripts/teardown.sh
TXT
