"""Substack-ops Textual TUI.

6 tabs: Notes / Posts / Comments / Feed / Auto / Profile
Sub-tabs (1/2/3): mine / following / general
Keys: tab, 1-3, ↑/↓, enter, r (reply), l (like), s (restack), o (open browser), q/esc
"""

from __future__ import annotations

import webbrowser
from typing import Any

try:  # pragma: no cover (TUI is optional)
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.widgets import (
        DataTable,
        Footer,
        Header,
        Static,
        TabbedContent,
        TabPane,
    )
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Textual is not installed. Run: uv pip install 'substack-ops[tui]' "
        "or `uv pip install textual`"
    ) from exc


from substack_ops.client import SubstackClient


class SubstackOpsTUI(App):
    CSS = """
    Screen { background: $surface; }
    DataTable { height: 1fr; }
    .panel { border: round $accent; padding: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("r", "reply", "Reply"),
        Binding("l", "like", "Like"),
        Binding("s", "restack", "Restack"),
        Binding("o", "open_browser", "Open in browser"),
        Binding("1", "subtab(1)", "Mine"),
        Binding("2", "subtab(2)", "Following"),
        Binding("3", "subtab(3)", "General"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.client: SubstackClient | None = None
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def on_mount(self) -> None:
        try:
            self.client = SubstackClient.create()
        except Exception as exc:  # noqa: BLE001
            self.notify(f"Auth error: {exc}", severity="error")
            self.exit()
            return
        self._refresh("notes")
        self._refresh("posts")
        self._refresh("feed")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab-notes"):
            with TabPane("Notes (1)", id="tab-notes"):
                yield DataTable(id="notes-table", cursor_type="row")
            with TabPane("Posts (2)", id="tab-posts"):
                yield DataTable(id="posts-table", cursor_type="row")
            with TabPane("Comments (3)", id="tab-comments"):
                yield Vertical(
                    Static("Pick a post in the Posts tab, then come back here to view its comments.", classes="panel"),
                    DataTable(id="comments-table", cursor_type="row"),
                )
            with TabPane("Feed (4)", id="tab-feed"):
                yield DataTable(id="feed-table", cursor_type="row")
            with TabPane("Auto (5)", id="tab-auto"):
                yield Vertical(
                    Static("Automation presets:", classes="panel"),
                    DataTable(id="auto-table", cursor_type="row"),
                )
            with TabPane("Profile (6)", id="tab-profile"):
                yield Static(id="profile-panel", classes="panel")
        yield Footer()

    def _refresh(self, tab: str) -> None:
        if not self.client:
            return
        if tab == "notes":
            items = self.client.list_notes(limit=20)
            self._cache["notes"] = items
            table = self.query_one("#notes-table", DataTable)
            table.clear(columns=True)
            table.add_columns("id", "date", "body", "replies")
            for n in items:
                comment = n.get("comment") or n
                body = (comment.get("body") or "").replace("\n", " ")[:80]
                table.add_row(
                    str(comment.get("id") or n.get("id")),
                    (comment.get("date") or "")[:10],
                    body,
                    str(comment.get("reply_count") or 0),
                )
        elif tab == "posts":
            items = self.client.list_posts(limit=20)
            self._cache["posts"] = items
            table = self.query_one("#posts-table", DataTable)
            table.clear(columns=True)
            table.add_columns("id", "date", "title", "comments")
            for p in items:
                table.add_row(
                    str(p.get("id")),
                    (p.get("post_date") or "")[:10],
                    (p.get("title") or "")[:60],
                    str(p.get("comment_count") or 0),
                )
        elif tab == "feed":
            items = self.client.get_feed(tab="for-you", limit=20)
            self._cache["feed"] = items
            table = self.query_one("#feed-table", DataTable)
            table.clear(columns=True)
            table.add_columns("type", "id", "body")
            for it in items:
                comment = it.get("comment") or {}
                body = (comment.get("body") or it.get("title") or "").replace("\n", " ")
                table.add_row(
                    it.get("type") or "?",
                    str(comment.get("id") or it.get("id") or ""),
                    body[:90],
                )

    def action_subtab(self, n: int) -> None:
        self.notify(f"sub-tab {n} (mine/following/general) — wiring TBD")

    def action_reply(self) -> None:
        self.notify("reply — bind to bulk_draft flow", severity="information")

    def action_like(self) -> None:
        self.notify("like — wires to react_to_post / react_to_note")

    def action_restack(self) -> None:
        self.notify("restack — wires to restack_post / restack_note")

    def action_open_browser(self) -> None:
        url = "https://substack.com"
        try:
            tab_id = self.query_one(TabbedContent).active
            if tab_id == "tab-posts":
                table = self.query_one("#posts-table", DataTable)
                row_idx = table.cursor_row
                items = self._cache.get("posts") or []
                if 0 <= row_idx < len(items):
                    url = items[row_idx].get("canonical_url") or url
            elif tab_id == "tab-notes":
                items = self._cache.get("notes") or []
                table = self.query_one("#notes-table", DataTable)
                row_idx = table.cursor_row
                if 0 <= row_idx < len(items):
                    cid = (items[row_idx].get("comment") or items[row_idx]).get("id")
                    if cid:
                        url = f"https://substack.com/@me/note/c-{cid}"
            webbrowser.open(url)
        except Exception:
            webbrowser.open(url)


def run() -> None:
    app = SubstackOpsTUI()
    app.run()


if __name__ == "__main__":
    run()
