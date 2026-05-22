# wt-wrangler

Local web app to list, search, summon and close Windows Terminal tabs from the browser. Windows Terminal is driven externally (Win32 + UI Automation) and never modified. Windows only. Released under MIT; intended for `uv tool install git+https://github.com/forensicmike/wt-wrangler`.

## Architecture
- **Package:** importable as `wt_wrangler`; distribution name `wt-wrangler`. Built with hatchling. Two identical console scripts → `wt_wrangler.server:main`: `wt-wrangler` and the short alias `wtw`.
- **Backend:** FastAPI + Uvicorn on `127.0.0.1:22222`. No database — state is read live from the OS on every request. `/healthz` is a cheap liveness probe the launcher uses.
  - `wt_wrangler/server.py` — the CLI. `wtw` (default `start`) spawns the server as a **detached** background process (`subprocess.DETACHED_PROCESS`, stdio → `%LOCALAPPDATA%\wt-wrangler\server.log`, pid in `server.pid`), waits on `/healthz`, then returns. Also `stop` (taskkill the pid), `status`, `open`, and `--foreground`/`--serve` (internal, run attached). `python -m wt_wrangler --serve` (via `__main__.py`) is what the detached process runs.
  - `run.py` (repo root) — dev launcher from a checkout (foreground). Auto-reload is intentionally **off** (a reload watcher watches the cwd, which we don't want).
- **Frontend:** No-build. Plain static `index.html` / `css` / `js` under `wt_wrangler/static/`, served by `StaticFiles` (deliberately *not* SCSS/Jinja, per the "statically provided" requirement). ES6 modules, dark mode, modals instead of `alert`, localStorage for the search filter and live-refresh toggle.
- **WT integration:** `wt_wrangler/wt.py`. Windows found via `EnumWindows` filtered on `CASCADIA_HOSTING_WINDOW_CLASS`; tabs read via native UIA `FindAll`. A tab is referenced by `(hwnd, tab_idx)` and re-resolved on each call (UIA COM elements don't survive across requests). UIA objects are thread-local because FastAPI runs sync endpoints on a thread pool and COM pointers can't cross threads.

## Conventions
- Add API routes in `wt_wrangler/main.py`; keep them small and verb-oriented (`list_tabs` / `summon` / `close`) so they're easy to wrap as chatbot tool calls later. The `StaticFiles` mount at `/` stays last so `/api/*` wins.
- Put OS/UIA logic in `wt_wrangler/wt.py`, not in routes. `HOST`/`PORT` live in `wt_wrangler/main.py`.
- Frontend logic lives in `wt_wrangler/static/js/app.js`; styling in `wt_wrangler/static/css/styles.css`. Static files must stay inside the package so they ship as wheel data.
- SCSS compilation is **not** part of this project — the CSS is hand-authored static.
- Run `ruff check` (and `ruff format`) after Python changes and fix issues before finishing.

## Known limitations
- PID↔tab association is unreliable (WT runs all windows in one process); this app intentionally keys tabs by window+index, not PID.
- Summoning across virtual desktops or from a minimized state may need hardening of `_force_foreground`.
