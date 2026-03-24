# Contributing (Article Monitor)

This guide describes development workflow, commands, environment setup, and testing.

Source of truth requested by command:
- `article-monitor/package.json` (scripts): **not present in this repository**
- `article-monitor/.env.example`

## Development Workflow

1. Work from `article-monitor/` (application root).
2. Create and activate virtual environment.
3. Install dependencies and Playwright Chromium.
4. Copy `.env.example` to `.env` and set required values.
5. Follow TDD for code changes:
   - RED: write failing test
   - GREEN: implement minimal fix
   - REFACTOR: clean up and keep tests passing
6. Run test suite and compile checks before commit.

## Commands / Scripts Reference

Because `package.json` does not exist, there is no `scripts` section to render.

| Source | Script | Description |
|---|---|---|
| `package.json` | N/A | `package.json` not found in this repo |

Operational commands used by this Python project (manual commands):

| Task | Command |
|---|---|
| Start app | `python run_monitor.py` |
| Run tests | `python -m pytest tests/ -q` |
| Coverage (80% gate) | `python -m pytest --cov=monitor --cov-fail-under=80 -q` |
| Compile check | `python -m compileall monitor` |
| Install Playwright Chromium | `python -m playwright install chromium` |

## Environment Setup

From `article-monitor/`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```

## Environment Variables (`.env.example`)

### Logging

| Variable | Purpose | Format / Default |
|---|---|---|
| `ARTICLE_MONITOR_DEBUG_LOG` | Optional debug log file path | string; empty disables file logging |

### Crawl

| Variable | Purpose | Format / Default |
|---|---|---|
| `CRAWL_INTERVAL_HOURS` | Crawl interval (hours) | int, default `6` |
| `CRAWL_TIMEOUT` | Request timeout (seconds) | int, default `60` |
| `CRAWL_CONCURRENCY` | Crawl concurrency | int (1-10), default `5` |
| `CRAWL_DELAY` | Delay between requests | number, default `1` |
| `CRAWL_CONCURRENCY_PER_DOMAIN` | Max per-domain concurrency (`0` = unlimited) | int, default `1` |
| `CRAWL_INTERLEAVE_BY_SITE` | Round-robin by site | bool, default `True` |
| `CRAWL_MIN_DELAY_PER_DOMAIN` | Minimum delay between same-domain requests (`0` = no limit) | number, default `0` |
| `CRAWL_MAX_RETRIES` | Max retries | int, default `10` |
| `CRAWL_RETRY_DELAY` | Retry base delay | number, default `2` |
| `CRAWL_RETRY_BACKOFF` | Retry backoff factor | number, default `1.5` |
| `CRAWL_RETRY_MAX_DELAY` | Retry max delay | number, default `30` |
| `CRAWL_RETRY_JITTER` | Add retry jitter | bool, default `True` |
| `CRAWL_RETRY_NETWORK_MAX` | Max network retries | int, default `10` |
| `CRAWL_RETRY_PARSE_MAX` | Max parse retries | int, default `3` |
| `CRAWL_RETRY_SSL_MAX` | Max SSL retries | int, default `5` |
| `CRAWL_RETRY_SSL_DELAY` | SSL retry delay | number, default `5` |

### Anti-scraping

| Variable | Purpose | Format / Default |
|---|---|---|
| `ANTI_SCRAPING_ENABLED` | Enable anti-scraping strategies | bool, default `True` |
| `ANTI_SCRAPING_ROTATE_UA` | Rotate User-Agent | bool, default `True` |
| `ANTI_SCRAPING_RANDOM_DELAY` | Randomized delays | bool, default `True` |
| `ANTI_SCRAPING_STEALTH_MODE` | Stealth mode | bool, default `True` |
| `ANTI_SCRAPING_MIN_DELAY` | Random delay min | number, default `1.0` |
| `ANTI_SCRAPING_MAX_DELAY` | Random delay max | number, default `5.0` |
| `ANTI_SCRAPING_UA_ROTATION_MIN` | UA rotation lower bound | int, default `10` |
| `ANTI_SCRAPING_UA_ROTATION_MAX` | UA rotation upper bound | int, default `30` |

### Flask

| Variable | Purpose | Format / Default |
|---|---|---|
| `FLASK_HOST` | Bind host | default `127.0.0.1` |
| `FLASK_PORT` | HTTP port | int, default `5001` |
| `FLASK_DEBUG` | Debug mode | bool, default `False` |

### Platform whitelist

| Variable | Purpose | Format / Default |
|---|---|---|
| `ALLOWED_PLATFORMS` | Allowed crawl platforms | comma-separated values; empty uses default whitelist |

### Feishu Bitable (optional)

| Variable | Purpose | Format / Default |
|---|---|---|
| `FEISHU_APP_ID` | Feishu app id | string |
| `FEISHU_APP_SECRET` | Feishu app secret | string |
| `FEISHU_BITABLE_APP_TOKEN` | Default Bitable app token | string |
| `FEISHU_BITABLE_TABLE_ID` | Default Bitable table id | string |
| `FEISHU_BITABLE_FIELD_URL` | URL column name | default `发布链接` |
| `FEISHU_BITABLE_FIELD_TOTAL_READ` | Total reads column name | default `总阅读量` |
| `FEISHU_BITABLE_FIELD_READ_24H` | 24h reads column name | default `24小时阅读量` |
| `FEISHU_BITABLE_FIELD_READ_72H` | 72h reads column name | default `72小时总阅读量` |
| `FEISHU_BITABLE_FIELD_ERROR` | Error column name | default `失败原因` |
| `FEISHU_BITABLE_ERROR_MESSAGE_MAX_LEN` | Max error message length to write back | int (100-500), default `200` |

## Testing Procedures

- Run all tests: `python -m pytest tests/ -q`
- Run coverage: `python -m pytest --cov=monitor --cov-report=term-missing -q`
- Enforce coverage floor: `python -m pytest --cov=monitor --cov-fail-under=80 -q`
- Run compile validation: `python -m compileall monitor`

Recommended pre-PR check:

```bash
python -m pytest --cov=monitor --cov-fail-under=80 -q && python -m compileall monitor
```
