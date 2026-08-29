#!/usr/bin/env bash
# Deploiement ACC sur Google Cloud (Doc 09).
# Usage : PROJECT_ID=xxx ./scripts/deploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID est requis}"
REGION="${REGION:-europe-west1}"
REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/acc"

echo "▸ Configuration du projet"
gcloud config set project "${PROJECT_ID}"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "▸ Build et push des images"
gcloud builds submit --tag "${REPO}/acc-mock-enterprise:latest" \
  --config=/dev/stdin <<YAML
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build','-f','infrastructure/docker/Dockerfile.mock','-t','${REPO}/acc-mock-enterprise:latest','.']
images: ['${REPO}/acc-mock-enterprise:latest']
YAML

gcloud builds submit --config=/dev/stdin <<YAML
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build','-f','infrastructure/docker/Dockerfile.api','-t','${REPO}/acc-api:latest','.']
images: ['${REPO}/acc-api:latest']
YAML

echo "▸ Provisionnement de l'infrastructure"
cd infrastructure/terraform
terraform init -upgrade
terraform apply \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="image_api=${REPO}/acc-api:latest" \
  -var="image_mock=${REPO}/acc-mock-enterprise:latest"

echo "▸ ACC deploye :"
terraform output -raw acc_api_url
