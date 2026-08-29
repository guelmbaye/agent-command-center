# ============================================================================
# ACC — Autonomous Mission Control : infrastructure Google Cloud (Doc 09)
# Principes : scale to zero, moindre privilege, etat durable hors compute.
# ============================================================================
terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  # Appliqués à toutes les ressources facturables pour la ventilation des coûts.
  cost_labels = {
    app         = "acc"
    environment = var.acc_env
    managed-by  = "terraform"
  }

  services = [
    "run.googleapis.com",
    "firestore.googleapis.com",
    "pubsub.googleapis.com",
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudtrace.googleapis.com",
    "modelarmor.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)
  service  = each.value

  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "acc" {
  location      = var.region
  repository_id = "acc"
  format        = "DOCKER"
  description   = "Images ACC (control plane + systemes simules)"

  depends_on = [google_project_service.enabled]
}
