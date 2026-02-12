# Data Models and Schemas

**Freshness:** 2026-02-12T09:35:00Z

## Storage

- **Database:** SQLite, single file (`data/monitor.db` by default).
- **Options:** WAL, NORMAL synchronous, cache_size from config (e.g. 2MB low-resource, 64MB default), temp_store=MEMORY, foreign_keys=ON.

## Tables (db/connection.py init_db)

### articles

| Column | Type | Notes |
|--------|------|--------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| url | TEXT | UNIQUE NOT NULL |
| title | TEXT | |
| site | TEXT | |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP |
| last_status | TEXT | DEFAULT 'PENDING' (migration) |
| last_error | TEXT | (migration) |
| last_crawl_time | TIMESTAMP | (migration) |

### read_counts

| Column | Type | Notes |
|--------|------|--------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| article_id | INTEGER | NOT NULL, FK → articles(id) |
| count | INTEGER | NOT NULL |
| timestamp | TIMESTAMP | DEFAULT (datetime('now', 'localtime')) |

Indexes: `idx_article_id`, `idx_timestamp`.

### settings

| Column | Type | Notes |
|--------|------|--------|
| key | TEXT | PRIMARY KEY |
| value | TEXT | NOT NULL |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP |

Seed: `crawl_interval_hours` from config.

## Repository Layer

- **article_repo:** articles CRUD + get_all_articles_with_latest_count, get_platform_failures, get_all_failures, get_failure_stats.
- **read_count_repo:** read_counts CRUD, get_latest_read_count(s)_batch, get_aggregated_read_counts, get_all_read_counts_summary, clear_cache, get_platform_health.
- **settings_repo:** get_setting, set_setting (key/value).

## External (Feishu Bitable)

- Sync with multi-column table; field names configurable (e.g. 发布链接, 总阅读量, 24小时阅读量, 72小时总阅读量, 失败原因).
- feishu_client: list/update/batch_update records; bitable_sync maps local articles ↔ Bitable rows by URL.
