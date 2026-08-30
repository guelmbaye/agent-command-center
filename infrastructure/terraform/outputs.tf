output "acc_api_url" {
  description = "URL du control plane ACC"
  value       = google_cloud_run_v2_service.api.uri
}

output "acc_mock_url" {
  description = "URL des systemes entreprise simules"
  value       = google_cloud_run_v2_service.mock.uri
}

output "artifact_registry" {
  description = "Depot d'images a utiliser pour les builds"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.acc.repository_id}"
}

output "acc_web_url" {
  description = "URL de Mission Control"
  value       = google_cloud_run_v2_service.web.uri
}

output "acc_api_key_command" {
  description = "How to read the generated API key (never printed here)"
  value = format(
    "gcloud secrets versions access latest --secret=acc-api-key --project=%s",
    var.project_id,
  )
}
