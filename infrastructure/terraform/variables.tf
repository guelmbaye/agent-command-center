variable "project_id" {
  description = "Projet Google Cloud hebergeant ACC"
  type        = string
}

variable "region" {
  description = "Region Cloud Run / Firestore"
  type        = string
  default     = "europe-west1"
}

variable "image_api" {
  description = "Image Artifact Registry du control plane"
  type        = string
}

variable "image_mock" {
  description = "Image Artifact Registry des systemes entreprise simules"
  type        = string
}

variable "acc_env" {
  type    = string
  default = "demo"
}

variable "agent_mode" {
  description = <<-EOT
    adk | hybrid | deterministic

    `hybrid` calls Gemini and falls back to the deterministic path on failure.
    Each call takes 10-20 s, so a full hero scenario runs about two minutes —
    half of a four-minute video spent watching spinners.

    `deterministic` exercises the SAME Gateway, the same policy decisions and
    the same audit trail with no model call at all, in under a second.

    Use `hybrid` to show the model reasoning. Use `deterministic` when the
    clock is the constraint, which includes the recording.
  EOT
  type        = string
  default     = "deterministic"

  validation {
    condition     = contains(["adk", "hybrid", "deterministic"], var.agent_mode)
    error_message = "agent_mode must be adk, hybrid or deterministic."
  }
}

variable "gemini_model" {
  description = "Modele Gemini. EXIGENCE DU CONCOURS : 3.5 ou plus recent."
  type        = string
  default     = "gemini-3.6-flash"
}

variable "image_web" {
  description = "Image Artifact Registry de Mission Control"
  type        = string
}

variable "max_instances_api" {
  description = "Plafond d'instances du control plane — garde-fou de coût"
  type        = number
  default     = 4
}

variable "monthly_budget_usd" {
  description = "Indicative monthly budget, reported by scripts/costs.py"
  type        = number
  default     = 50
}

variable "cors_origin_regex" {
  description = "Origins allowed by regex. Cloud Run subdomains are generated at deploy time, so an exact list is not enough."
  type        = string
  default     = "https://acc-(web|api)-[a-z0-9-]+\\.(a\\.)?run\\.app|https://acc-(web|api)-[0-9]+\\.[a-z0-9-]+\\.run\\.app"
}

variable "cors_origins" {
  description = "Extra exact origins, comma separated. Usually empty: Cloud Run URLs are matched by cors_origin_regex."
  type        = string
  default     = ""
}
