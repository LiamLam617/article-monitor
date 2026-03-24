# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Article Monitor is a monolithic Python/Flask web application that periodically scrapes article read/view counts from Chinese tech blogging platforms (Juejin, CSDN, CNBlogs, 51CTO, SegmentFault, Jianshu, etc.). It provides a web dashboard, REST API, SQLite storage, CSV export, and optional Feishu Bitable sync.

All application code lives under `article-monitor/`. The entry point is `article-monitor/run_monitor.py`.

### Running the application

```bash
cd /workspace/article-monitor
source .venv/bin/activate
FLASK_HOST=0.0.0.0 FLASK_PORT=5001 python run_monitor.py
```

The app is accessible at `http://localhost:5001`. It starts both the Flask web server and APScheduler for periodic crawling.

### Important caveats

- **POST /api/articles** immediately crawls the submitted URL using Playwright/Chromium. This can take 30-60 seconds per article. Use `--max-time 120` with curl.
- **Tests** live under repository-root `tests/` (pytest). Run from `article-monitor/` with `python -m pytest tests/ -q`. Test tooling includes pytest, pytest-cov, and pytest-asyncio.
- **Playwright Chromium** must be installed in the venv: `python -m playwright install chromium`. The browser is cached at `~/.cache/ms-playwright/`.
- **SQLite** is embedded (file at `article-monitor/data/monitor.db`); no external database needed.
- **Feishu Bitable sync** is optional and requires `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, etc. environment variables.

### Commands reference

See `docs/CONTRIB.md` for the full command table. Key commands (run from `article-monitor/`):

| Task | Command |
|------|---------|
| Lint/compile check | `python -m compileall monitor` |
| Run tests | `python -m pytest tests/ -q` |
| Tests + coverage | `python -m pytest --cov=monitor --cov-report=term-missing -q` |
| Start server | `python run_monitor.py` |
| Health check | `curl http://localhost:5001/api/monitor/health` |
