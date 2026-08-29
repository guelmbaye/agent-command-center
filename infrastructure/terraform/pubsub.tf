# ============================================================================
# Bus d'evenements : l'execution longue ne depend d'aucune requete HTTP.
# ============================================================================
resource "google_pubsub_topic" "events" {
  name = "acc-events"

  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_topic" "dead_letter" {
  name = "acc-events-dlq"
}

resource "google_pubsub_subscription" "engine" {
  name  = "acc-events-engine"
  topic = google_pubsub_topic.events.id

  # Le Mission Engine est idempotent : une redelivery ne double aucune action.
  ack_deadline_seconds       = 60
  message_retention_duration = "86400s"

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.api.uri}/api/v1/events/pubsub"

    oidc_token {
      service_account_email = google_service_account.pubsub_invoker.email
    }
  }

  retry_policy {
    minimum_backoff = "5s"
    maximum_backoff = "300s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }
}
