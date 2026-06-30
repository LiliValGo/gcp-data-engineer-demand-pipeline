variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID where resources will be deployed."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "The GCP region to deploy resources to (e.g. us-central1)."
}

variable "gcs_bucket_name" {
  type        = string
  default     = ""
  description = "Custom name for the GCS Bronze bucket. If empty, defaults to {project_id}-job-market-bronze."
}

variable "google_api_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Google Gemini API key for intelligent role variant generation."
}
