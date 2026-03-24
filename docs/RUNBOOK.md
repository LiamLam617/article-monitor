# Article Monitor Runbook

This runbook covers deployment, monitoring/alerts, common incidents, and rollback.

## Deployment Procedures

### 1) Prepare runtime

From `article-monitor/`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```

### 2) Configure required variables

Minimum for app startup:
- `FLASK_HOST`
- `FLASK_PORT`
- `FLASK_DEBUG`

Minimum for Feishu Bitable sync:
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- and either:
  - defaults in env: `FEISHU_BITABLE_APP_TOKEN` + `FEISHU_BITABLE_TABLE_ID`, or
  - provide `app_token` + `table_id` in `POST /api/bitable/sync` body.

### 3) Start service

```bash
python run_monitor.py
```

### 4) Post-deploy checks

- Health: `GET /api/monitor/health`
- Articles API: `GET /api/articles`
- Optional smoke crawl: `POST /api/crawl`

## Monitoring and Alerts

### Health endpoint

- Probe `GET /api/monitor/health` periodically (for example every 1 minute).
- Alert when:
  - HTTP status is not `200`
  - response `success` is false
  - CPU / memory / disk exceed your thresholds

### Failure monitoring

- Failed records: `GET /api/failures`
- Failure stats: `GET /api/failures/stats`
- Retry single failure: `POST /api/failures/retry/<article_id>`

Alert suggestions:
- failure count spike in 10-15 minute window
- persistent platform-specific failures
- long-running task backlog growth

### Bitable sync operational limits

`POST /api/bitable/sync` now runs async task submission with shared crawl pool behavior.

Current guardrails:
- per source (`app_token + table_id`) rate limit: 60s
- global endpoint burst limit: 2s
- max inflight sync tasks: 20

Expected throttling response:
- status `429`
- error like `请求过于频繁，请稍后再试` or `同步任务过多，请稍后再试`

## Common Issues and Fixes

### Service fails to start

Checks:
- virtual environment activated
- dependencies installed
- no port conflict on `FLASK_PORT`
- no syntax/import errors (`python -m compileall monitor`)

### Playwright Chromium missing

Symptom:
- errors indicating browser executable missing

Fix:

```bash
python -m playwright install chromium
```

### Crawls are slow or timing out

Tune:
- `CRAWL_TIMEOUT`
- `CRAWL_CONCURRENCY`
- `CRAWL_DELAY`
- `CRAWL_MAX_RETRIES` and `CRAWL_RETRY_*`
- `CRAWL_CONCURRENCY_PER_DOMAIN`
- `CRAWL_MIN_DELAY_PER_DOMAIN`

Notes:
- Bitable sync crawl uses per-URL timeout protection. Timeout URLs are marked as failed and do not block the whole task.
- Check `GET /api/tasks/<task_id>` → `data.progress.errors` for timeout entries (for example `爬取超时（>60秒）`).

### Bitable sync returns 400

Likely causes:
- missing `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
- missing `app_token` / `table_id` (neither in env nor request body)

### Bitable sync returns 429

Likely causes:
- repeated calls for same source within 60s
- calls too frequent globally (<2s apart)
- inflight limit reached (20 active sync tasks)

### Disk pressure from SQLite growth

- database file: `article-monitor/data/monitor.db`
- perform periodic backup + retention cleanup policy

## Rollback Procedures

### Code rollback

```bash
git checkout <previous-stable-commit>
```

### Dependency rollback

If requirements changed:

```bash
pip install -r requirements.txt
```

### Data safety

- backup `article-monitor/data/monitor.db` before risky release
- if schema incompatibility occurs, restore from known-good backup and document delta

### Restart and validate

After rollback:
- start app (`python run_monitor.py`)
- verify:
  - `GET /api/monitor/health`
  - `GET /api/articles`
  - optional `POST /api/crawl`
