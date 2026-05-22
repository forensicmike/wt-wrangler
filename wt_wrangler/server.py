"""Console entry point for the ``wt-wrangler`` / ``wtw`` commands.

By default the command launches the server as a **detached background
process** (no console, output redirected to a log file), waits until it
answers, prints that it's up, and returns — so it doesn't tie up a terminal.
Use ``wtw stop`` / ``wtw status`` to manage it, or ``wtw --foreground`` to run
it attached to the current terminal for debugging.
"""

from __future__ import annotations

import argparse
import os
import subprocess  # noqa: S404
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from wt_wrangler.main import HOST, PORT, app

URL = f"http://{HOST}:{PORT}"
STATE_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "wt-wrangler"
PID_FILE = STATE_DIR / "server.pid"
LOG_FILE = STATE_DIR / "server.log"


def _is_up(timeout: float = 0.5) -> bool:
    """Return True if a wt-wrangler server is already answering on the port."""
    try:
        with urllib.request.urlopen(f"{URL}/healthz", timeout=timeout) as resp:  # noqa: S310
            return b"wt-wrangler" in resp.read(64)
    except Exception:
        return False


def _serve() -> None:
    """Run the server in the foreground (the detached process runs this)."""
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def _spawn_detached() -> int:
    """Start the server in a detached, windowless background process.

    ``pythonw.exe`` is the GUI-subsystem interpreter and never creates a
    console window (``DETACHED_PROCESS`` alone can still flash one under
    Windows Terminal). Fall back to ``python.exe`` + ``CREATE_NO_WINDOW`` if
    ``pythonw.exe`` isn't next to the current interpreter.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_FILE.open("ab")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if pythonw.exists():
        launcher = str(pythonw)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        launcher = sys.executable
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(  # noqa: S603
        [launcher, "-m", "wt_wrangler", "--serve"],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    PID_FILE.write_text(str(proc.pid))
    return proc.pid


def start(*, open_browser: bool = True) -> None:
    """Ensure the background server is running, then open the UI."""
    if _is_up():
        print(f"wt-wrangler already running at {URL}")
        if open_browser:
            webbrowser.open(URL)
        return
    _spawn_detached()
    for _ in range(60):  # wait up to ~6s for it to come up
        if _is_up():
            print(f"wt-wrangler is up at {URL}  (logs: {LOG_FILE})")
            if open_browser:
                webbrowser.open(URL)
            return
        time.sleep(0.1)
    print(f"wt-wrangler was started but isn't answering yet — check {LOG_FILE}")


def stop() -> None:
    """Stop the background server, if running."""
    pid = None
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
        except ValueError:
            pid = None
    if not pid and not _is_up():
        print("wt-wrangler is not running")
        return
    if pid:
        taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
        subprocess.run(  # noqa: S603
            [str(taskkill), "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    PID_FILE.unlink(missing_ok=True)
    print("wt-wrangler stopped")


def status() -> None:
    """Print whether the server is currently running."""
    print(f"wt-wrangler: {'running' if _is_up() else 'stopped'}  ({URL})")


def main() -> None:
    """Parse arguments and dispatch the requested action."""
    parser = argparse.ArgumentParser(
        prog="wtw", description="Browse, search, summon and close Windows Terminal tabs.",
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="start",
        choices=["start", "stop", "status", "open"],
        help="start (default), stop, status, or open the UI",
    )
    parser.add_argument(
        "--foreground", action="store_true", help="run attached to this terminal (don't detach)",
    )
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.serve:  # internal: invoked inside the detached process
        _serve()
    elif args.action == "stop":
        stop()
    elif args.action == "status":
        status()
    elif args.action == "open":
        webbrowser.open(URL)
    elif args.foreground:
        print(f"wt-wrangler  ->  {URL}")
        if not args.no_browser:
            webbrowser.open(URL)
        _serve()
    else:
        start(open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
