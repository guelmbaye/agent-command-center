# ============================================================================
# Identite d'agent : chaque service a son propre principal, au plus juste.
# Aucune cle de service n'est generee (Workload Identity uniquement).
# ============================================================================
resource "google_service_account" "api" {
  account_id   = "acc-api"
  display_name = "ACC Control Plane"
  description  = "Mission Engine, Agent Gateway, Policy Engine"
}

resource "google_service_account" "mock" {
  account_id   = "acc-mock-enterprise"
  display_name = "ACC Mock Enterprise Systems"
}

resource "google_service_account" "pubsub_invoker" {
  account_id   = "acc-pubsub-invoker"
  display_name = "ACC Pub/Sub push invoker"
}

locals {
  api_roles = [
    "roles/datastore.user",          # Firestore : etat de mission
    "roles/pubsub.publisher",        # continuation asynchrone
    "roles/aiplatform.user",         # Gemini via Vertex AI
    "roles/cloudtrace.agent",        # traces de mission
    "roles/logging.logWriter",
    "roles/secretmanager.secretAccessor",
    "roles/modelarmor.user",         # sanitizeUserPrompt / sanitizeModelResponse
    "roles/monitoring.metricWriter", # metriques de mission
  ]
}

resource "google_project_iam_member" "api" {
  for_each = toset(local.api_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "mock_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.mock.email}"
}

# Le control plane est le seul appelant autorise du systeme entreprise.
resource "google_cloud_run_v2_service_iam_member" "api_calls_mock" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.mock.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.api.email}"
}

# Pub/Sub push : seul ce principal peut invoquer /api/v1/events/pubsub.
resource "google_cloud_run_v2_service_iam_member" "pubsub_calls_api" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_invoker.email}"
}
