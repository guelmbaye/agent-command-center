# Aucun secret dans le code ni dans les variables d'environnement en clair.
resource "google_secret_manager_secret" "api_key" {
  secret_id = "acc-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret" "pubsub_push_token" {
  secret_id = "acc-pubsub-push-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}
