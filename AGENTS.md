## Learned User Preferences
- Prefer Docker configuration pared down to core functionality; keep extras like Tor/proxy fallbacks optional or removed by default.
- When asking for “unnecessary files/code”, prefer an answer grouped by “core vs optional” (with clear deletion safety notes).

## Learned Workspace Facts
- Application code lives under `article-monitor/`; the entry point is `article-monitor/run_monitor.py`.
- Tests live under repo-root `tests/` (not under `article-monitor/`).
- On Windows, `monitor` imports during pytest typically require running from `article-monitor/` and targeting `../tests`, or setting `PYTHONPATH` appropriately.
- The workspace shell is PowerShell; avoid bashisms like `&&` and heredocs when suggesting commands.
