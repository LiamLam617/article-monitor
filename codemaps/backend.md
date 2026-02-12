# Backend Structure

**Freshness:** 2026-02-12T09:35:00Z

## Entry & App

| File | Purpose |
|------|--------|
| `run_monitor.py` | Imports `monitor.app.app`, `monitor.config`; starts scheduler then `app.run()` |
| `monitor/__init__.py` | Re-exports `app`, config constants, `init_db` |
| `monitor/app.py` | Flask app, CORS; routes for articles, crawl, settings, statistics, tasks, failures, export, bitable sync, health |

## Routes (app.py)

| Method | Path | Handler | Notes |
|--------|------|---------|--------|
| GET | `/` | index | render index.html |
| GET | `/favicon.ico` | favicon | 204 |
| GET | `/api/articles` | get_articles | get_all_articles_with_latest_count |
| POST | `/api/articles/batch` | create_articles_batch | async task or sync for ≤5 URLs |
| POST | `/api/articles` | create_article | single URL |
| DELETE | `/api/articles/<id>` | remove_article | |
| GET | `/api/articles/<id>/history` | get_history | read_counts for article |
| POST | `/api/crawl` | manual_crawl | trigger crawl_all_sync |
| POST | `/api/crawl/stop` | stop_crawl | stop_crawling() |
| GET | `/api/crawl/progress` | get_crawl_progress | |
| GET | `/api/settings` | get_settings | |
| POST | `/api/settings` | update_settings | |
| GET | `/api/statistics` | get_statistics | |
| GET | `/api/tasks/<task_id>` | get_task_status | |
| DELETE | `/api/tasks/<task_id>` | cancel_task | |
| GET | `/api/failures` | get_failures | |
| POST | `/api/failures/retry/<id>` | retry_failure | |
| POST | `/api/export/csv` | export_csv | body: article_ids |
| GET | `/api/export/all-csv` | export_all_csv | |
| POST | `/api/bitable/sync` | bitable_sync | rate-limited |
| GET | `/api/monitor/health` | get_system_health | health_service |

## Core Modules

| Module | Depends On | Exports / Role |
|--------|------------|----------------|
| config | os, platform_rules | CRAWL_*, BROWSER_POOL_*, SQLITE_CACHE_*, FEISHU_*, is_platform_allowed |
| database | db.connection, db.article_repo, db.read_count_repo, db.settings_repo | init_db, add_article, get_all_articles, get_all_articles_with_latest_count, add_read_count, get_read_counts, get_latest_read_count, get_setting, set_setting, add_articles_batch, add_read_counts_batch, get_platform_health, get_platform_failures, get_all_failures, get_failure_stats, CRUD articles |
| scheduler | apscheduler, crawler.crawl_all_sync, database.get_setting | start_scheduler, get_interval_hours, update_schedule, stop_scheduler |
| crawler | database, extractors, config, anti_scraping | crawl_all_sync, crawl_all_articles, get_crawl_progress, stop_crawling, reset_crawl_progress |
| extractors | crawl4ai, config, anti_scraping | get_browser_config, ensure_browser_config, create_shared_crawler, extract_article_info, extract_read_count, extract_with_config, extract_with_config_full |
| browser_pool | crawl4ai, extractors, config | get_browser_pool, BrowserPool |
| anti_scraping | - | get_anti_scraping_manager, reset_anti_scraping_manager, get_random_user_agent, get_random_viewport, get_human_delay, BrowserProfile, AntiScrapingManager, MouseSimulator |
| article_service | config, task_manager, browser_pool, extractors, database, url_utils | _process_urls_async, _process_urls_sync, crawl_urls_for_results |
| task_manager | - | get_task_manager, TaskManager, TaskStatus |
| export_service | database | export_selected_articles_csv, export_all_articles_csv |
| health_service | config, database, psutil | get_system_health_payload |
| feishu_client | lark_oapi, config | list_bitable_records, list_all_bitable_records, update_bitable_record, batch_update_bitable_records, truncate_error_message |
| bitable_sync | article_service, config, feishu_client | sync_from_bitable |
| url_utils | urllib.parse, config | normalize_url, validate_url, validate_and_normalize_url |
| platform_rules | - | PLATFORM_EXTRACTORS (dict by site) |

## DB Package (monitor/db)

| File | Purpose |
|------|--------|
| connection.py | get_db(), init_db(), _apply_db_optimizations; SQLite WAL, PRAGMA cache_size from config |
| article_repo.py | add_article, get_all_articles, get_all_articles_with_latest_count, add_articles_batch, get_article_by_id, delete_article, update_article_title, get_article_by_url, update_article_status, get_platform_failures, get_all_failures, get_failure_stats |
| read_count_repo.py | add_read_count, add_read_counts_batch, get_read_counts, get_latest_read_count, get_latest_read_counts_batch, delete_read_count_by_timestamp, get_aggregated_read_counts, get_all_read_counts_summary, clear_cache, get_platform_health |
| settings_repo.py | get_setting, set_setting |
