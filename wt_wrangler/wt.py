"""Windows Terminal discovery and control via Win32 + UI Automation.

No modification to Windows Terminal is required. Windows are found with the
Win32 ``EnumWindows`` API (filtering on the WT host window class), and their
tabs are read with native UIA ``FindAll`` calls. Tabs are referenced from the
client by ``(hwnd, tab_idx)`` and re-resolved on every request, since UIA COM
elements do not survive across HTTP calls.
"""

from __future__ import annotations

import ctypes
import re
import threading
from ctypes import wintypes

import comtypes
import comtypes.client

comtypes.client.GetModule("UIAutomationCore.dll")
from comtypes.gen import UIAutomationClient as UIA  # noqa: E402

WT_WINDOW_CLASS = "CASCADIA_HOSTING_WINDOW_CLASS"
GW_OWNER = 4
SW_RESTORE = 9
_MAX_CLASS_NAME = 256

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_tls = threading.local()


def _automation() -> UIA.IUIAutomation:
    """Return a thread-local IUIAutomation, initialising COM on first use.

    FastAPI runs sync endpoints on a thread pool; each worker thread needs its
    own COM apartment and its own automation object (COM pointers must not be
    shared across threads).
    """
    uia = getattr(_tls, "uia", None)
    if uia is None:
        comtypes.CoInitialize()
        uia = comtypes.client.CreateObject(
            UIA.CUIAutomation, interface=UIA.IUIAutomation,
        )
        _tls.uia = uia
    return uia


# --------------------------------------------------------------------------
# Window discovery (Win32) and tab reading (native UIA FindAll)
# --------------------------------------------------------------------------
def _enum_top_windows() -> list[int]:
    """Return handles of all top-level windows."""
    hwnds: list[int] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd: int, _lparam: int) -> bool:
        hwnds.append(hwnd)
        return True

    _user32.EnumWindows(proc(_cb), 0)
    return hwnds


def _class_name(hwnd: int) -> str:
    """Return the Win32 class name for a window handle."""
    buf = ctypes.create_unicode_buffer(_MAX_CLASS_NAME)
    _user32.GetClassNameW(hwnd, buf, _MAX_CLASS_NAME)
    return buf.value


def _wt_window_hwnds() -> list[int]:
    """Return handles of visible, non-owned Windows Terminal host windows."""
    out: list[int] = []
    for hwnd in _enum_top_windows():
        if (
            _user32.IsWindowVisible(hwnd)
            and _class_name(hwnd) == WT_WINDOW_CLASS
            and not _user32.GetWindow(hwnd, GW_OWNER)
        ):
            out.append(hwnd)
    return out


def _tab_items(uia: UIA.IUIAutomation, window_elem: object) -> list:
    """Return the TabItem UIA elements under a window, in tab order."""
    cond = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_TabItemControlTypeId,
    )
    arr = window_elem.FindAll(UIA.TreeScope_Descendants, cond)
    return [arr.GetElement(i) for i in range(arr.Length)]


def _is_selected(tab_elem: object) -> bool:
    """Return True if the tab is the focused tab in its window."""
    try:
        pat = tab_elem.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
        sel = pat.QueryInterface(UIA.IUIAutomationSelectionItemPattern)
        return bool(sel.CurrentIsSelected)
    except OSError:
        return False


def list_tabs() -> list[dict]:
    """List every tab across all Windows Terminal windows.

    Returns:
        A list of dicts with ``hwnd``, ``win_idx`` (1-based window number),
        ``tab_idx`` (position within the window), ``title`` and ``focused``.
    """
    uia = _automation()
    tabs: list[dict] = []
    for win_idx, hwnd in enumerate(_wt_window_hwnds(), 1):
        try:
            window = uia.ElementFromHandle(hwnd)
        except OSError:
            continue
        for tab_idx, tab in enumerate(_tab_items(uia, window)):
            tabs.append(
                {
                    "hwnd": int(hwnd),
                    "win_idx": win_idx,
                    "tab_idx": tab_idx,
                    "title": tab.CurrentName or "",
                    "focused": _is_selected(tab),
                },
            )
    return tabs


def _resolve_tab(uia: UIA.IUIAutomation, hwnd: int, tab_idx: int) -> object | None:
    """Re-resolve a tab element by window handle and position."""
    try:
        window = uia.ElementFromHandle(hwnd)
    except OSError:
        return None
    items = _tab_items(uia, window)
    return items[tab_idx] if 0 <= tab_idx < len(items) else None


def _force_foreground(hwnd: int) -> None:
    """Raise a window to the foreground, working around the focus lock.

    Briefly attaching the calling thread's input queue to the current
    foreground window's thread is the standard way to make
    ``SetForegroundWindow`` succeed from a background process.
    """
    fg = _user32.GetForegroundWindow()
    cur = _kernel32.GetCurrentThreadId()
    fg_thread = _user32.GetWindowThreadProcessId(fg, None)
    tgt_thread = _user32.GetWindowThreadProcessId(hwnd, None)
    _user32.AttachThreadInput(cur, fg_thread, True)
    _user32.AttachThreadInput(cur, tgt_thread, True)
    try:
        _user32.ShowWindow(hwnd, SW_RESTORE)
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        _user32.AttachThreadInput(cur, fg_thread, False)
        _user32.AttachThreadInput(cur, tgt_thread, False)


def summon(hwnd: int, tab_idx: int) -> bool:
    """Select a tab and bring its window to the foreground."""
    uia = _automation()
    tab = _resolve_tab(uia, hwnd, tab_idx)
    if tab is None:
        return False
    try:
        pat = tab.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
        pat.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
    except OSError:
        return False
    _force_foreground(hwnd)
    return True


def _find_close_button(uia: UIA.IUIAutomation, tab_elem: object) -> object | None:
    """Find the per-tab close button inside a TabItem subtree."""
    cond = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_ButtonControlTypeId,
    )
    arr = tab_elem.FindAll(UIA.TreeScope_Descendants, cond)
    buttons = [arr.GetElement(i) for i in range(arr.Length)]
    for button in buttons:
        try:
            if button.CurrentAutomationId == "CloseButton":
                return button
        except OSError:
            continue
    return buttons[0] if buttons else None


def close(hwnd: int, tab_idx: int) -> bool:
    """Close a tab by invoking its close button."""
    uia = _automation()
    tab = _resolve_tab(uia, hwnd, tab_idx)
    if tab is None:
        return False
    button = _find_close_button(uia, tab)
    if button is None:
        return False
    try:
        pat = button.GetCurrentPattern(UIA.UIA_InvokePatternId)
        pat.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
    except OSError:
        return False
    return True


def sort_key(title: str) -> str:
    """Alphabetical sort key for a tab title, ignoring leading status glyphs."""
    stripped = re.sub(r"^[^0-9A-Za-z]+", "", title).lower()
    return stripped or title.lower()
