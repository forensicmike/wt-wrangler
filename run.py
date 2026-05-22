"""Development launcher: runs the server from a checkout.

For normal use after ``uv tool install`` just run the ``wt-wrangler`` command
(see ``wt_wrangler/server.py``). This script is a convenience for working on
the code from a checkout. Auto-reload is intentionally off: a reload watcher
watches the working directory, which is noise we don't want for a tool like
this.
"""

from __future__ import annotations

import uvicorn

from wt_wrangler.main import HOST, PORT, app


def main() -> None:
    """Run the server (no auto-reload)."""
    print(f"wt-wrangler (dev)  ->  http://{HOST}:{PORT}")  # noqa: T201
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
