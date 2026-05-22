"""FastAPI application: JSON API plus the static single-page frontend.

The API is intentionally small and verb-oriented so it is trivial to wrap as
tool calls for a future chatbot feature: ``list_tabs``, ``summon``, ``close``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from wt_wrangler import wt

HOST = "127.0.0.1"
PORT = 22222
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="wt-wrangler", description="Windows Terminal tab manager")


class TabRef(BaseModel):
    """Reference to a specific tab by window handle and position."""

    hwnd: int
    tab_idx: int


class ActionResult(BaseModel):
    """Result of a summon/close action."""

    ok: bool


@app.get("/healthz")
def healthz() -> dict:
    """Cheap liveness probe used by the launcher to detect a running server."""
    return {"app": "wt-wrangler", "ok": True}


@app.get("/api/tabs")
def get_tabs() -> dict:
    """List every open Windows Terminal tab across all windows."""
    return {"tabs": wt.list_tabs()}


@app.post("/api/summon")
def post_summon(ref: TabRef) -> ActionResult:
    """Bring a tab's window to the front and select that tab."""
    return ActionResult(ok=wt.summon(ref.hwnd, ref.tab_idx))


@app.post("/api/close")
def post_close(ref: TabRef) -> ActionResult:
    """Close a tab (this may end a running shell)."""
    return ActionResult(ok=wt.close(ref.hwnd, ref.tab_idx))


# Mounted last so the /api routes above take precedence over the SPA.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
