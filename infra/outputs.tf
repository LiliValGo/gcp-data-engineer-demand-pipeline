output "artifact_registry_repo" {
  value       = google_artifact_registry_repository.repo.repository_id
  description = "Artifact Registry Repository Name"
}

output "gcs_bucket_name" {
  value       = google_storage_bucket.bronze.name
  description = "GCS Bronze Bucket Name"
}

output "web_ui_url" {
  value       = google_cloud_run_v2_service.web.uri
  description = "URL of the FastAPI Web UI Explorer"
}

output "mcp_server_url" {
  value       = google_cloud_run_v2_service.mcp.uri
  description = "URL of the MCP Server (SSE Endpoint: /sse)"
}
