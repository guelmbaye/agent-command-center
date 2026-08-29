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
  description = "adk | hybrid | deterministic"
  type        = string
  default     = "hybrid"
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
  description = "Budget mensuel indicatif, utilisé par scripts/costs.sh"
  type        = number
  default     = 50
}
