provider "google" {
  project = var.project_id
  region  = var.region
}

# ── 1. Artifact Registry ──────────────────────────────────────────────────────
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "job-market-pipeline"
  description   = "Docker images for Scraper and Web App"
  format        = "DOCKER"
}

# ── 2. Cloud Storage Bucket (Bronze Layer) ───────────────────────────────────
resource "google_storage_bucket" "bronze" {
  name                        = var.gcs_bucket_name != "" ? var.gcs_bucket_name : "${var.project_id}-job-market-bronze"
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type = "Delete"
    }
  }
}

# ── 3. BigQuery Datasets (Silver & Gold Layers) ──────────────────────────────
resource "google_bigquery_dataset" "silver" {
  dataset_id                 = "silver"
  friendly_name              = "Silver Layer"
  description                = "Cleaned deduplicated job postings"
  location                   = var.region
  delete_contents_on_destroy = true
}

resource "google_bigquery_dataset" "gold" {
  dataset_id                 = "gold"
  friendly_name              = "Gold Layer"
  description                = "Aggregated job market metrics for MCP / Claude"
  location                   = var.region
  delete_contents_on_destroy = true
}

# ── 4. Secret Manager (Gemini API Key) ───────────────────────────────────────
resource "google_secret_manager_secret" "gemini_key" {
  secret_id = "gemini-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "gemini_key_version" {
  count       = var.google_api_key != "" ? 1 : 0
  secret      = google_secret_manager_secret.gemini_key.id
  secret_data = var.google_api_key
}

# ── 5. IAM & Service Accounts ────────────────────────────────────────────────
resource "google_service_account" "pipeline_sa" {
  account_id   = "job-market-pipeline-sa"
  display_name = "Service Account for Job Market Pipeline"
}

resource "google_storage_bucket_iam_member" "gcs_writer" {
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.admin"
  member = "serviceAccount:${google_service_account.pipeline_sa.email}"
}

resource "google_project_iam_member" "bq_admin" {
  project = var.project_id
  role    = "roles/bigquery.admin"
  member  = "serviceAccount:${google_service_account.pipeline_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "secret_reader" {
  secret_id = google_secret_manager_secret.gemini_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.pipeline_sa.email}"
}

# ── 6. Cloud Run Job (Scraper + dbt run) ─────────────────────────────────────
resource "google_cloud_run_v2_job" "scraper" {
  name     = "job-scraper"
  location = var.region

  template {
    template {
      service_account = google_service_account.pipeline_sa.email
      containers {
        # Overwritten during CI/CD or direct push; using a placeholder image for init
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/scraper:latest"

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "GCS_BUCKET"
          value = google_storage_bucket.bronze.name
        }
        env {
          name  = "SEARCH_TERMS"
          value = "[\"data engineer\", \"data analyst\", \"desarrollador devops\"]"
        }

        env {
          name = "GOOGLE_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.gemini_key.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image
    ]
  }
}

# ── 7. Cloud Run Service (FastAPI Web Explorer) ──────────────────────────────
resource "google_cloud_run_v2_service" "web" {
  name     = "job-explorer-web"
  location = var.region

  template {
    service_account = google_service_account.pipeline_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/web:latest"

      ports {
        container_port = 8080
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "FASTAPI_HOST"
        value = "0.0.0.0"
      }
      env {
        name  = "FASTAPI_PORT"
        value = "8080"
      }

      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image
    ]
  }
}

resource "google_cloud_run_service_iam_member" "public_web" {
  location = google_cloud_run_v2_service.web.location
  service  = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── 8. Cloud Run Service (MCP Server SSE) ────────────────────────────────────
resource "google_cloud_run_v2_service" "mcp" {
  name     = "job-explorer-mcp"
  location = var.region

  template {
    service_account = google_service_account.pipeline_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/web:latest"

      ports {
        container_port = 8080
      }

      command = ["python", "run_mcp.py"]

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "MCP_TRANSPORT"
        value = "sse"
      }
      env {
        name  = "PORT"
        value = "8080"
      }

      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image
    ]
  }
}

resource "google_cloud_run_service_iam_member" "public_mcp" {
  location = google_cloud_run_v2_service.mcp.location
  service  = google_cloud_run_v2_service.mcp.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── 9. Cloud Scheduler (Daily Trigger) ───────────────────────────────────────
resource "google_service_account" "scheduler_sa" {
  account_id   = "job-scheduler-sa"
  display_name = "Service Account for Cloud Scheduler Trigger"
}

resource "google_project_iam_member" "scheduler_run_jobs" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

resource "google_cloud_scheduler_job" "daily_scraper" {
  name             = "daily-job-scraper-trigger"
  description      = "Trigger the daily job scraper and dbt transformations"
  schedule         = "0 6 * * *"
  time_zone        = "UTC"
  attempt_deadline = "320s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.scraper.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }
}
