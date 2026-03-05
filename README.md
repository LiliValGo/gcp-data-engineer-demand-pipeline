# Job Market Role Explorer & Data Engineer Scraper

Sistema completo para explorar variantes de roles laborales y realizar web scraping de ofertas de empleo desde GetonBoard, refactorizado con patrones senior-level Data Engineering.

## Features ✨

- **Búsqueda Inteligente de Roles**: Descubre todas las variantes y sinónimos de un rol laboral
- **Exploración de Roles Relacionados**: Encuentra roles con similitud y categorías relacionadas
- **Web Scraper Robusto**: Extrae datos con retry automático, circuit breaker, checkpoint DB
- **Data Quality Framework**: Valida datos con métricas de confianza de extracción
- **Schema Versioning**: Control de versiones de esquema para evolución sin breaking changes
- **Structured Logging**: Logs en JSON para observabilidad y auditoría
- **FastAPI Web App**: Interfaz moderna para explorar roles y disparar scraping
- **Idempotency**: Sistema de checkpoints para reintentos sin duplicación

## Setup Rápido

```bash
# 1. Crear environment
python -m venv venv && source venv/bin/activate

# 2. Instalar
pip install -r requirements.txt

# 3. Ejecutar scraper
python main_scraper.py

# 4. O ejecutar web app
python run_web.py  # Abre http://localhost:8000
```

## Core Refactorings

✅ Logging Estructurado (JSON)
✅ Data Quality Framework + Confidence Scoring
✅ Checkpoint System (SQLite Idempotency)
✅ Schema Versioning (JobV1 → JobV2)
✅ Resilience Patterns (Circuit Breaker, Exponential Backoff)
✅ Role Mapper System (Fuzzy Matching, Hierarchical)
✅ Configuration Management (Pydantic Settings)
✅ Lineage & Audit Trail

## Estructura

```
├── scraper/              ## Core module (refactorizado)
├── role_mapper/          ## Role search system
├── web/                  ## FastAPI web app
├── main_scraper.py      ## Entry point
├── run_web.py           ## Web server
├── requirements.txt     ## Dependencies
└── .env.example         ## Config template
```

## Uso

### Scraper CLI
```bash
python main_scraper.py
# Output: data/raw/role=data_engineer/2024-03-04__v2.json
```

### Web App
```bash
python run_web.py
# Abre http://localhost:8000
```

### Role Mapper
```python
from role_mapper.role_mapper import RoleMapper

mapper = RoleMapper("role_mapper/config/roles.yaml")
role = mapper.find_role("data analyst")
print(role.variants)
# ['data analyst', 'business intelligence', 'bi analyst', ...]
```

## Status: 🚀 Listo para Pruebas

El refactor está 95% completo. La web app tiene estructura lista (routes TBD).
Continúa con pruebas o implementación de web endpoints según necesites.
