# Contributing to Article Monitor

Development workflow, available scripts, environment setup, and testing. Single source of truth: `article-monitor/.env.example`, `article-monitor/run_monitor.py`, `article-monitor/scripts/`, `article-monitor/monitor/config.py`.

## Development environment

- **Python**: 3.11+
- **Working directory**: `article-monitor/` (repo root is one level up)

### Setup

1. Create virtual environment and install dependencies:

   **Option A – PowerShell script (Windows)**  
   From repo root:
   ```powershell
   .\article-monitor\scripts\install_venv.ps1
   ```
   Then activate: `article-monitor\.venv\Scripts\Activate.ps1`

   **Option B – Manual**
   ```bash
   cd article-monitor
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate  # Linux/macOS
   pip install -r monitor/requirements.txt
   ```

2. (Required for crawl) Install Playwright Chromium:
   ```bash
   python -m playwright install chromium
   ```

3. Copy env template and set values as needed:
   ```bash
   cp .env.example .env
   ```

Application code lives in `monitor/`; tests in `tests/`.

---

## Available scripts / commands

No `package.json`; all commands are Python/shell. Run from `article-monitor/` unless noted.

| Action | Command | Description |
|--------|---------|-------------|
| Install venv + deps | `scripts/install_venv.ps1` (from repo root) | Creates `.venv`, installs from `monitor/requirements.txt` |
| Start web app | `python run_monitor.py` | Starts Flask + scheduler (default `127.0.0.1:5001`) |
| Start from module | `cd monitor && python -m flask --app app run` or run `app.py` | Alternative start; port from env |
| Run all tests | `python -m pytest tests/ -q` | Pytest, quiet |
| Tests + coverage | `python -m pytest --cov=monitor --cov-report=term-missing -q` | Coverage report |
| Coverage 80% gate | `python -m pytest --cov=monitor --cov-fail-under=80 -q` | Fails if under 80% (see `.coveragerc`) |
| Single test file | `python -m pytest tests/test_xxx.py -v` | One file, verbose |
| Compile check | `python -m compileall monitor` | Syntax check |

---

## Environment variables

Defined in `monitor/config.py`; template: `article-monitor/.env.example`. Do not commit secrets; use `.env` (gitignored) or system env.

| Variable | Purpose | Format / default |
|----------|----------|-------------------|
| `ARTICLE_MONITOR_DEBUG_LOG` | Optional debug log file path | Path string; empty = disabled |
| `CRAWL_INTERVAL_HOURS` | Crawl interval (hours) | Integer, default `6` |
| `CRAWL_TIMEOUT` | Request timeout (seconds) | Integer, default `60` |
| `CRAWL_CONCURRENCY` | Concurrent crawl requests (capped 1–10) | Integer, default `5` |
| `CRAWL_DELAY` | Delay between requests (seconds) | Float, default `1` |
| `CRAWL_CONCURRENCY_PER_DOMAIN` | Max concurrent per domain; 0 = no limit | Integer, default `1` |
| `CRAWL_INTERLEAVE_BY_SITE` | Round-robin by site | `True`/`False`, default `True` |
| `CRAWL_MIN_DELAY_PER_DOMAIN` | Min delay between same-domain requests (seconds) | Float, default `0` |
| `CRAWL_MAX_RETRIES` | Max retries (network) | Integer, default `10` |
| `CRAWL_RETRY_DELAY` | Retry delay (seconds) | Float, default `2` |
| `CRAWL_RETRY_BACKOFF` | Backoff multiplier | Float, default `1.5` |
| `CRAWL_RETRY_MAX_DELAY` | Max retry delay (seconds) | Float, default `30` |
| `CRAWL_RETRY_JITTER` | Add jitter to retries | `True`/`False`, default `True` |
| `CRAWL_RETRY_NETWORK_MAX` | Max retries for network errors | Integer, default `10` |
| `CRAWL_RETRY_PARSE_MAX` | Max retries for parse errors | Integer, default `3` |
| `CRAWL_RETRY_SSL_MAX` | Max retries for SSL errors | Integer, default `5` |
| `CRAWL_RETRY_SSL_DELAY` | Fixed delay for SSL retries (seconds) | Float, default `5` |
| `ANTI_SCRAPING_ENABLED` | Enable anti-scraping behaviour | `True`/`False`, default `True` |
| `ANTI_SCRAPING_ROTATE_UA` | Rotate User-Agent | `True`/`False`, default `True` |
| `ANTI_SCRAPING_RANDOM_DELAY` | Random delay between requests | `True`/`False`, default `True` |
| `ANTI_SCRAPING_STEALTH_MODE` | Stealth mode (hide automation) | `True`/`False`, default `True` |
| `ANTI_SCRAPING_MIN_DELAY` | Min random delay (seconds) | Float, default `1.0` |
| `ANTI_SCRAPING_MAX_DELAY` | Max random delay (seconds) | Float, default `5.0` |
| `ANTI_SCRAPING_UA_ROTATION_MIN` | UA rotation interval (requests) | Integer, default `10` |
| `ANTI_SCRAPING_UA_ROTATION_MAX` | UA rotation interval (requests) | Integer, default `30` |
| `FLASK_HOST` | Flask bind address | Default `127.0.0.1` |
| `FLASK_PORT` | Flask port | Integer, default `5001` |
| `FLASK_DEBUG` | Flask debug mode | `True`/`False`, default `False` |
| `ALLOWED_PLATFORMS` | Platform whitelist (comma-separated) | e.g. `juejin,csdn,cnblog`; empty = default list |
| `FEISHU_APP_ID` | Feishu app ID (Bitable sync) | String |
| `FEISHU_APP_SECRET` | Feishu app secret | String |
| `FEISHU_BITABLE_APP_TOKEN` | Bitable app token | String |
| `FEISHU_BITABLE_TABLE_ID` | Bitable table ID | String |
| `FEISHU_BITABLE_FIELD_URL` | Bitable column name for URL | Default `发布链接` |
| `FEISHU_BITABLE_FIELD_TOTAL_READ` | Bitable column for total read count | Default `总阅读量` |
| `FEISHU_BITABLE_FIELD_READ_24H` | Bitable column for 24h read | Default `24小时阅读量` |
| `FEISHU_BITABLE_FIELD_READ_72H` | Bitable column for 72h read | Default `72小时总阅读量` |
| `FEISHU_BITABLE_FIELD_ERROR` | Bitable column for error message | Default `失败原因` |
| `FEISHU_BITABLE_ERROR_MESSAGE_MAX_LEN` | Max length of error written to Bitable (100–500) | Integer, default `200` |

---

## Development workflow

1. **Branch**  
   Create a feature/fix branch (e.g. `feat/bitable-sync`, `fix/export-bom`).

2. **TDD**  
   - RED: write failing test  
   - GREEN: minimal implementation to pass  
   - REFACTOR: clean up, extract helpers  

3. **Quality**  
   - Keep functions &lt; 50 lines, files &lt; 800 lines  
   - Prefer immutable data; validate all external input  
   - No hardcoded secrets; no debug prints in committed code  

4. **Before commit**  
   - `python -m pytest --cov=monitor -q`  
   - `python -m compileall monitor`  
   - Ensure no CRITICAL/HIGH issues from security/code review

---

## Testing

- **Run all tests (from `article-monitor/`)**  
  ```bash
  python -m pytest tests/ -q
  ```

- **With coverage and 80% gate**  
  ```bash
  python -m pytest --cov=monitor --cov-report=term-missing --cov-fail-under=80 -q
  ```
  Config: `.coveragerc` (source `monitor`, excludes `tests/`, `extractors.py`, `anti_scraping.py`).

- **HTML coverage report**  
  ```bash
  python -m pytest --cov=monitor --cov-report=html -q
  ```
  Open `htmlcov/index.html`.

- **Single file**  
  ```bash
  python -m pytest tests/test_app_routes.py -v
  ```

Target: core modules (e.g. `crawler`, `article_service`, `url_utils`) ≥ 80% coverage; extractors/anti_scraping excluded due to browser/UA complexity.

---

## Pull requests

- Describe what changed and why; note test commands and any impact on API/DB/crawl behaviour.
- Pre-merge checks: tests pass, no hardcoded secrets, coverage acceptable.
