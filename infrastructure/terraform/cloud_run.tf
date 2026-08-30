# ============================================================================
# Services Cloud Run — scale to zero, plafond d'instances strict (Doc 09 §22)
# ============================================================================
resource "google_cloud_run_v2_service" "mock" {
  name     = "acc-mock-enterprise"
  location = var.region

  # Provider v6 defaults to deletion_protection = true, which blocks BOTH a
  # replacement and `terraform destroy`. For a demo environment that is exactly
  # backwards: the service must be replaceable after a failed revision, and
  # `make teardown` must be able to bring billing back to zero.
  deletion_protection = false
  # NOT internal-only: a Cloud Run service calling another over its public URL
  # leaves the Google network and comes back, so internal-only ingress rejects
  # it — with a 404 that reads like a missing route, not a blocked request.
  # Access stays restricted by IAM: only acc-api holds run.invoker (iam.tf).
  ingress  = "INGRESS_TRAFFIC_ALL"

  # Labels de coût : permettent de ventiler la facture par composant
  # (Rapports de facturation -> Grouper par -> Label).
  labels = local.cost_labels

  template {
    service_account = google_service_account.mock.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.image_mock

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      ports {
        container_port = 8080
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_cloud_run_v2_service" "api" {
  name     = "acc-api"
  location = var.region

  # Provider v6 defaults to deletion_protection = true, which blocks BOTH a
  # replacement and `terraform destroy`. For a demo environment that is exactly
  # backwards: the service must be replaceable after a failed revision, and
  # `make teardown` must be able to bring billing back to zero.
  deletion_protection = false
  ingress  = "INGRESS_TRAFFIC_ALL"

  labels = merge(local.cost_labels, { component = "control-plane" })

  template {
    service_account = google_service_account.api.email

    # Les missions durent plus qu'une requete : le bus prend le relais,
    # mais on laisse de la marge pour le streaming SSE.
    timeout = "900s"

    scaling {
      min_instance_count = 0 # scale to zero : aucun cout a l'inactivite
      max_instance_count = var.max_instances_api # plafond strict de cout
    }

    containers {
      image = var.image_api

      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "ACC_ENV"
        value = var.acc_env
      }
      env {
        name  = "ACC_PERSISTENCE"
        value = "firestore"
      }
      env {
        name  = "ACC_EVENT_BUS"
        value = "pubsub"
      }
      env {
        name  = "ACC_AGENT_MODE"
        value = var.agent_mode
      }
      env {
        name  = "ACC_MODEL_ARMOR"
        value = "gcp"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_REGION"
        value = var.region
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "1"
      }
      env {
        name  = "VERTEX_AI_LOCATION"
        value = var.region
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "PUBSUB_TOPIC"
        value = google_pubsub_topic.events.name
      }
      env {
        name  = "ACC_ENTERPRISE_BASE_URL"
        value = google_cloud_run_v2_service.mock.uri
      }
      env {
        name  = "OTEL_TRACES_EXPORTER"
        value = "gcp"
      }
      # CORS. Without these the control plane allows no origin in cloud mode,
      # and the browser blocks every call from Mission Control — while `curl`
      # keeps working, which is exactly how this stayed invisible.
      #
      # Deliberately NOT `google_cloud_run_v2_service.web.uri`: referencing the
      # web service from the API creates a Terraform dependency cycle as soon
      # as anything points back. The regex already covers both Cloud Run URL
      # formats, so no cross-service reference is needed at all.
      #
      # Starlette does NOT expand wildcards in allow_origins, hence the regex.
      env {
        name  = "ACC_CORS_ORIGINS"
        value = var.cors_origins
      }
      env {
        name  = "ACC_CORS_ORIGIN_REGEX"
        value = var.cors_origin_regex
      }

      env {
        name  = "ACC_DEMO_MODE"
        value = "1"
      }

      # Secrets injectes depuis Secret Manager, jamais en clair.
      env {
        name = "ACC_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "PUBSUB_PUSH_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.pubsub_push_token.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
        initial_delay_seconds = 5
        failure_threshold     = 10
      }
    }
  }

  # Cloud Run reads `versions/latest`. Terraform infers a dependency on the
  # SECRET (via secret_id), never on its VERSION — so without listing the
  # versions here, the service can be created before any version exists and the
  # revision fails with:
  #   Secret .../acc-api-key/versions/latest was not found
  depends_on = [
    google_project_service.enabled,
    google_firestore_database.acc,
    google_secret_manager_secret_version.api_key,
    google_secret_manager_secret_version.pubsub_push_token,
  ]
}

# L'URL publique est protegee par cle d'API applicative (Doc 09 pro-tips).
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------------------
# Mission Control — interface operateur
# ---------------------------------------------------------------------------
resource "google_service_account" "web" {
  account_id   = "acc-web"
  display_name = "ACC Mission Control"
}

resource "google_cloud_run_v2_service" "web" {
  name     = "acc-web"
  location = var.region

  # Provider v6 defaults to deletion_protection = true, which blocks BOTH a
  # replacement and `terraform destroy`. For a demo environment that is exactly
  # backwards: the service must be replaceable after a failed revision, and
  # `make teardown` must be able to bring billing back to zero.
  deletion_protection = false
  ingress  = "INGRESS_TRAFFIC_ALL"

  labels = merge(local.cost_labels, { component = "mission-control" })

  template {
    service_account = google_service_account.web.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.image_web

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      ports {
        container_port = 8080
      }

      # NOTE: NEXT_PUBLIC_ACC_API is deliberately NOT set here. Next.js inlines
      # `NEXT_PUBLIC_*` at BUILD time, so a runtime variable has no effect
      # (ADR-045). It is passed as a --build-arg by scripts/deploy.py instead.
      #
      # Removing it also breaks a dependency cycle: the API service needs the
      # web URL for CORS, and the web service cannot need the API URL in return.
    }
  }

  depends_on = [google_cloud_run_v2_service.api]
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
