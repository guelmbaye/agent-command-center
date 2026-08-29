#!/usr/bin/env bash
# Démantèlement complet d'ACC — ramène la facturation à zéro.
#
# Le seul moyen fiable d'arrêter les coûts après le hackathon.
# Usage :  PROJECT_ID=xxx ./scripts/teardown.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID est requis}"
REGION="${REGION:-europe-west1}"

printf '\033[91m⚠ Ceci détruit toute l'\''infrastructure ACC du projet %s\033[0m\n' "${PROJECT_ID}"
read -r -p "Taper le nom du projet pour confirmer : " CONFIRM
[[ "${CONFIRM}" == "${PROJECT_ID}" ]] || { echo "Annulé."; exit 1; }

echo "▸ Levée de la protection sur Firestore"
# Terraform ne peut pas détruire la base tant que la protection est active.
gcloud firestore databases update --database='(default)' \
  --no-delete-protection --project="${PROJECT_ID}" 2>/dev/null \
  || echo "  (protection déjà levée ou base absente)"

echo "▸ Destruction de l'infrastructure"
cd infrastructure/terraform
terraform destroy -auto-approve \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="image_api=unused" -var="image_mock=unused" -var="image_web=unused" \
  || echo "  (certaines ressources ont pu résister — voir ci-dessous)"
cd ../..

echo "▸ Vérification des ressources facturables restantes"
gcloud run services list --project="${PROJECT_ID}" --format='table(name,region)' 2>/dev/null || true
gcloud artifacts repositories list --project="${PROJECT_ID}" \
  --format='table(name,format,sizeBytes)' 2>/dev/null || true

cat <<TXT

Ce qui peut encore facturer après un destroy :
  · Images dans Artifact Registry (stockage)
      gcloud artifacts repositories delete acc --location=${REGION} --project=${PROJECT_ID}
  · Logs conservés dans Cloud Logging (rétention par défaut 30 j, souvent gratuits)
  · La base Firestore si la protection n'a pas pu être levée

Option nucléaire, garantie à zéro :
  gcloud projects delete ${PROJECT_ID}
TXT
