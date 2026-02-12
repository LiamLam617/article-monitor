# Frontend Structure

**Freshness:** 2026-02-12T09:35:00Z

## Overview

Single-page UI served by Flask. One HTML template with inline CSS/JS; no separate frontend build or framework.

## Assets

| Path | Description |
|------|-------------|
| `monitor/templates/index.html` | Single template: article list, add/delete, crawl, settings, statistics, failures, export, Bitable sync, health. Chart.js + chartjs-plugin-datalabels (CDN). |

## Stack

- **Templating:** Jinja2 (Flask default), single `index.html`
- **Charts:** Chart.js 4.4.0, chartjs-plugin-datalabels (CDN)
- **No:** React/Vue, npm build, or separate static bundling

## API Usage (from UI)

- GET `/api/articles` – list articles with latest read count
- POST `/api/articles`, POST `/api/articles/batch` – add articles
- DELETE `/api/articles/<id>` – remove article
- GET `/api/articles/<id>/history` – history for charts
- POST `/api/crawl`, GET `/api/crawl/progress` – manual crawl
- GET/POST `/api/settings` – crawl interval etc.
- GET `/api/statistics` – stats
- GET `/api/tasks/<id>`, DELETE `/api/tasks/<id>` – batch task status/cancel
- GET `/api/failures`, POST `/api/failures/retry/<id>` – failures
- POST `/api/export/csv`, GET `/api/export/all-csv` – CSV export
- POST `/api/bitable/sync` – Feishu Bitable sync
- GET `/api/monitor/health` – system health
