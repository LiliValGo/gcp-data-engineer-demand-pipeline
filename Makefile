.PHONY: install test scrape run-mcp dbt-run seed clean

# Default shell
SHELL := /bin/bash

# Default target
all: test

install:
	@echo "Running setup script..."
	chmod +x setup.sh
	./setup.sh

test:
	@echo "Running tests..."
	source venv/bin/activate && pytest tests/ -v

scrape:
	@echo "Running scraper..."
	source venv/bin/activate && python main_scraper.py

run-mcp:
	@echo "Running MCP server on SSE (port 8000)..."
	source venv/bin/activate && MCP_TRANSPORT=sse PORT=8000 python run_mcp.py

dbt-run:
	@echo "Running dbt locally on DuckDB..."
	source venv/bin/activate && cd transform && dbt run --target dev --profiles-dir .

seed:
	@echo "Seeding DuckDB with demo data..."
	source venv/bin/activate && python scripts/seed_demo_data.py

clean:
	@echo "Cleaning up temporary files and DuckDB target directories..."
	rm -rf transform/target/ transform/dbt_packages/
	rm -f data/pipeline.duckdb
	find . -type d -name "__pycache__" -exec rm -rf {} +
