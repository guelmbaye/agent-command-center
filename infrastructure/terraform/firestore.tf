# Etat de mission durable : le compute peut disparaitre, la mission non.
resource "google_firestore_database" "acc" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  # Protege contre une suppression accidentelle de la source de verite.
  delete_protection_state = "DELETE_PROTECTION_ENABLED"

  depends_on = [google_project_service.enabled]
}

# Index requis par GET /approvals?status=PENDING (index plat)
resource "google_firestore_index" "approvals_index" {
  project    = var.project_id
  database   = google_firestore_database.acc.name
  collection = "approvals_index"

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "requested_at"
    order      = "DESCENDING"
  }
}

# Index requis par GET /missions?status=...
resource "google_firestore_index" "missions_by_status" {
  project    = var.project_id
  database   = google_firestore_database.acc.name
  collection = "missions"

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}
