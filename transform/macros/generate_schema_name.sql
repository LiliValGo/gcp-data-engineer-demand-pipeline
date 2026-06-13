/*
  generate_schema_name.sql
  ─────────────────────────────────────────────────────────────────────────────
  Overrides dbt's default schema naming strategy.

  Default dbt behavior: {target.schema}_{custom_schema} → "main_gold"
  Our override:         use custom_schema directly        → "gold"

  Why override?
  - Locally we want exact schema names (gold, silver) to match what
    medallion.py wrote and what the MCP server queries.
  - In Phase 4 (BigQuery), the BigQuery adapter uses dataset names, so
    "gold" maps cleanly to the BigQuery dataset named "gold".
  - Without this, all Gold tables land in "main_gold" and the MCP tools
    querying "gold.*" would return empty results.

  Reference: https://docs.getdbt.com/docs/build/custom-schemas
*/

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
