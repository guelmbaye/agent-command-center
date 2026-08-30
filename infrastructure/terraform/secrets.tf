# ============================================================================
# Secrets — generated here, never committed, never passed on a command line.
#
# Terraform used to create the secret CONTAINERS only. A secret with no version
# has no `latest`, so Cloud Run refused to start:
#
#   Secret projects/.../secrets/acc-api-key/versions/latest was not found
#
# The values were meant to be created by hand with `openssl rand`. That is one
# more manual step, it is easy to skip, and `openssl` is not available in a
# default PowerShell. Terraform generates them instead: the deployment is
# self-contained.
# ============================================================================

resource "random_password" "api_key" {
  length  = 48
  special = false # copied by hand into .env.local and curl commands
}

resource "random_password" "pubsub_push_token" {
  length  = 48
  special = false
}

resource "google_secret_manager_secret" "api_key" {
  secret_id = "acc-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "api_key" {
  secret      = google_secret_manager_secret.api_key.id
  secret_data = random_password.api_key.result
}

resource "google_secret_manager_secret" "pubsub_push_token" {
  secret_id = "acc-pubsub-push-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "pubsub_push_token" {
  secret      = google_secret_manager_secret.pubsub_push_token.id
  secret_data = random_password.pubsub_push_token.result
}
