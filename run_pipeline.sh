#!/bin/bash
# Exit immediately if a command exits with a non-zero status
set -e

echo "=== Starting GCP Scraper Job ==="
python main_scraper.py

echo "=== Running dbt Transformations on BigQuery ==="
# BigQuery target 'prod' uses Application Default Credentials automatically
dbt run --project-dir transform --profiles-dir transform --target prod

echo "=== GCP Scraper & Transformation Job Finished Successfully ==="
