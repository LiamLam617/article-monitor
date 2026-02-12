# Architecture

**Freshness:** 2026-02-12T09:35:00Z

## Overview

Article Monitor is a Python Flask application that tracks article read counts across supported platforms (e.g. Juejin, CSDN, CNBlogs). It uses Crawl4AI/Playwright for browser-based extraction, SQLite for persistence, and optional Feishu Bitable sync.

## High-Level Structure

```
article-monitor/
├── run_monitor.py          # Entry: starts scheduler + Flask
└── monitor/
    ├── app.py              # Flask app, routes, CORS
    ├── config.py           # Env-based config, platform rules import
    ├── platform_rules.py   # Per-platform extractor config (PLATFORM_EXTRACTORS)
    ├── database.py         # Facade over db.* (articles, read_counts, settings)
    ├── db/                 # Connection + repositories
    ├── scheduler.py        # APScheduler → crawl_all_sync
    ├── crawler.py          # Async crawl loop, retry, domain rate limit
    ├── extractors.py       # Crawl4AI integration, read-count extraction
    ├── browser_pool.py     # Shared AsyncWebCrawler pool
    ├── anti_scraping.py    # UA rotation, stealth, delays
    ├── article_service.py  # Batch URL processing, task manager
    ├── task_manager.py     # Async task queue (batch add articles)
    ├── export_service.py   # CSV export
    ├── health_service.py   # System/monitor health API
    ├── feishu_client.py    # Lark Bitable API
    ├── bitable_sync.py     # Sync Bitable ↔ local articles
    ├── url_utils.py        # Normalize/validate URL, platform detection
    └── templates/
        └── index.html      # SPA-style UI (Chart.js, tabs)
```

## Dependency Flow

- **Entry:** `run_monitor.py` → `monitor.app.app`, `monitor.scheduler.start_scheduler`
- **HTTP:** `app.py` → database, article_service, export_service, health_service, url_utils, scheduler
- **Crawl:** scheduler → crawler → extractors, database, anti_scraping; crawler uses browser_pool via extractors
- **Data:** app/database → db.connection, db.article_repo, db.read_count_repo, db.settings_repo
- **Config:** config.py → platform_rules.PLATFORM_EXTRACTORS; many modules import config

## External Stack

- **Runtime:** Python 3.11, Flask, Flask-CORS, APScheduler, Crawl4AI (Playwright/Chromium), lark-oapi, psutil
- **Data:** SQLite (WAL), file path from config
- **Deploy:** Docker (Dockerfile + docker-compose), 2C2G-friendly (RESOURCE_PROFILE=low)
