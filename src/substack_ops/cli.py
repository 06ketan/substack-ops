"""substack-ops CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from substack_ops import __version__
from substack_ops.auth import AuthError, verify
from substack_ops.client import SubstackClient

console = Console()
err_console = Console(stderr=True, style="bold red")

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="substack-ops · CLI for managing your Substack content",
)

auth_app = typer.Typer(no_args_is_help=True, help="Authentication commands")
posts_app = typer.Typer(no_args_is_help=True, help="Post commands")
comments_app = typer.Typer(no_args_is_help=True, help="Comment commands")
notes_app = typer.Typer(no_args_is_help=True, help="Note commands")
reply_app = typer.Typer(
    no_args_is_help=True,
    help=(
        "Reply to comments. PREFERRED: connect MCP and use the propose_reply / "
        "confirm_reply tools from your IDE/desktop chat — no env vars needed.\n"
        "These CLI subcommands need a host LLM CLI (claude/cursor-agent/codex) "
        "on PATH (or SUBSTACK_OPS_LLM_CMD set)."
    ),
)
podcasts_app = typer.Typer(no_args_is_help=True, help="Podcast commands")
recs_app = typer.Typer(no_args_is_help=True, help="Recommendations")
authors_app = typer.Typer(no_args_is_help=True, help="Authors of a publication")
categories_app = typer.Typer(no_args_is_help=True, help="Substack categories")
users_app = typer.Typer(no_args_is_help=True, help="Public user profiles")
profile_app = typer.Typer(no_args_is_help=True, help="Your own profile")
feed_app = typer.Typer(no_args_is_help=True, help="Reader feed")
audit_app = typer.Typer(no_args_is_help=True, help="Audit log search")
auto_app = typer.Typer(no_args_is_help=True, help="Automation engine")

app.add_typer(auth_app, name="auth")
app.add_typer(posts_app, name="posts")
app.add_typer(comments_app, name="comments")
app.add_typer(notes_app, name="notes")
app.add_typer(reply_app, name="reply")
app.add_typer(podcasts_app, name="podcasts")
app.add_typer(recs_app, name="recommendations")
app.add_typer(authors_app, name="authors")
app.add_typer(categories_app, name="categories")
app.add_typer(users_app, name="users")
app.add_typer(profile_app, name="profile")
app.add_typer(feed_app, name="feed")
app.add_typer(audit_app, name="audit")
app.add_typer(auto_app, name="auto")


@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", "-V", is_eager=True),
) -> None:
    if version:
        console.print(f"substack-ops {__version__}")
        raise typer.Exit()


@auth_app.command("verify")
def auth_verify(
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON instead of table"),
    mcp_path: Path | None = typer.Option(
        None,
        "--mcp",
        help="Path to mcp.json (defaults to $SUBSTACK_OPS_MCP_PATH or ~/.cursor/mcp.json)",
    ),
) -> None:
    """Confirm we can talk to Substack as you."""
    try:
        result = verify(mcp_path=mcp_path)
    except AuthError as exc:
        err_console.print(f"AuthError: {exc}")
        raise typer.Exit(code=2) from exc
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"verify failed: {exc!r}")
        raise typer.Exit(code=1) from exc

    payload = {k: v for k, v in result.items() if k != "auth"}

    if json_out:
        console.print_json(data=payload)
        if not payload["ok"]:
            raise typer.Exit(code=1)
        return

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold cyan")
    table.add_column()
    status = "[bold green]OK[/]" if payload["ok"] else "[bold red]FAIL[/]"
    table.add_row("status", status)
    table.add_row("name", str(payload.get("name") or "?"))
    table.add_row("user_id", payload["user_id"])
    table.add_row("publication", payload["publication_url"])
    if payload.get("publication_name"):
        table.add_row("pub name", str(payload["publication_name"]))
    if payload.get("publication_id"):
        table.add_row("pub id", str(payload["publication_id"]))
    table.add_row("subscriptions", str(payload.get("subscriptions_count") or 0))
    table.add_row("api status", str(payload["subscriptions_status"]))
    console.print(table)

    if not payload["ok"]:
        raise typer.Exit(code=1)


@auth_app.command("test")
def auth_test(json_out: bool = typer.Option(False, "--json")) -> None:
    """Alias for `auth verify` (postcli parity)."""
    auth_verify(json_out=json_out, mcp_path=None)


@auth_app.command("login")
def auth_login(
    browser: str = typer.Option("chrome", "--browser", help="chrome | brave"),
    email: str | None = typer.Option(None, "--email", help="Use Email magic-link instead of Chrome"),
    out: Path = typer.Option(Path(".cache/cookies.json"), "--out"),
) -> None:
    """Auto-grab Substack cookies (Chrome/Brave Keychain) or send a magic link."""
    if email:
        from substack_ops.auth_otp import consume_magic_link, request_magic_link

        result = request_magic_link(email)
        console.print_json(data=result)
        link = typer.prompt("Paste the magic-link from your email")
        path = consume_magic_link(link, cookies_path=out)
        console.print(f"[green]wrote cookies to[/] {path}")
        return
    from substack_ops.auth_chrome import grab_cookies

    try:
        path = grab_cookies(browser=browser, out_path=out)
    except RuntimeError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=2) from exc
    console.print(f"[green]wrote cookies to[/] {path}")


@auth_app.command("setup")
def auth_setup(
    out: Path = typer.Option(Path(".cache/cookies.json"), "--out"),
) -> None:
    """Interactive paste-cookies flow for users without Chrome auto-grab."""
    sid = typer.prompt("Paste your substack.sid cookie value", hide_input=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {"name": "substack.sid", "value": sid, "domain": ".substack.com", "path": "/", "secure": True},
        {"name": "substack.lli", "value": "1", "domain": ".substack.com", "path": "/", "secure": True},
    ]
    out.write_text(json.dumps(payload, indent=2))
    try:
        import os as _os

        _os.chmod(out, 0o600)
    except OSError:
        pass
    console.print(f"[green]wrote cookies to[/] {out}. Now run [cyan]substack-ops auth verify[/].")


# ---------------------------------------------------------------------------
# posts
# ---------------------------------------------------------------------------

@posts_app.command("list")
def posts_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Max posts to fetch"),
    sort: str = typer.Option("new", "--sort", help="new | top | pinned | community"),
    pub: str | None = typer.Option(None, "--pub", help="Other publication subdomain"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List posts (yours by default; pass --pub to read another publication)."""
    with SubstackClient.create() as c:
        posts = c.list_posts(limit=limit, sorting=sort, pub=pub)

    if json_out:
        console.print_json(data=posts)
        return

    t = Table(title=f"Posts (limit={limit}, sort={sort})", show_lines=False)
    t.add_column("id", style="cyan", no_wrap=True)
    t.add_column("date", style="dim")
    t.add_column("type")
    t.add_column("title")
    t.add_column("comments", justify="right")
    t.add_column("reactions", justify="right")
    for p in posts:
        t.add_row(
            str(p.get("id")),
            (p.get("post_date") or "")[:10],
            p.get("type", "?"),
            (p.get("title") or "")[:60],
            str(p.get("comment_count") or 0),
            str(p.get("reaction_count") or 0),
        )
    console.print(t)


@posts_app.command("show")
def posts_show(
    post_id: str = typer.Argument(..., help="Numeric post id OR slug"),
    pub: str | None = typer.Option(None, "--pub"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show a single post's metadata."""
    with SubstackClient.create() as c:
        meta = c.get_post(post_id, pub=pub)
    if json_out:
        console.print_json(data=meta)
        return

    fields = [
        "id", "title", "subtitle", "type", "audience", "post_date",
        "comment_count", "reaction_count", "wordcount", "canonical_url",
    ]
    t = Table(show_header=False, box=None)
    t.add_column(style="bold cyan")
    t.add_column()
    for f in fields:
        if f in meta:
            t.add_row(f, str(meta[f])[:120])
    console.print(t)


@posts_app.command("stats")
def posts_stats(
    post_id: str = typer.Argument(..., help="Numeric post id"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Publisher stats for a post (opens, clicks, views, subs)."""
    with SubstackClient.create() as c:
        stats = c.get_post_stats(post_id)
    if json_out:
        console.print_json(data=stats)
        return
    t = Table(show_header=False, box=None, title=f"Stats post {post_id}")
    t.add_column(style="bold cyan")
    t.add_column()
    for k, v in stats.items():
        if k.startswith("_"):
            continue
        t.add_row(k, str(v)[:120])
    console.print(t)
    if stats.get("_note"):
        console.print(f"[dim italic]{stats['_note']}[/]")


@posts_app.command("content")
def posts_content(
    post_id: str = typer.Argument(..., help="Numeric post id OR slug"),
    md: bool = typer.Option(False, "--md", help="Render HTML to markdown"),
    pub: str | None = typer.Option(None, "--pub"),
    out: Path | None = typer.Option(None, "--out", help="Write to file instead of stdout"),
) -> None:
    """Fetch the body HTML for a post (markdownify with --md)."""
    with SubstackClient.create() as c:
        html = c.get_post_content(post_id, pub=pub)
    if html is None:
        err_console.print("no body content (paywalled and unauthed?)")
        raise typer.Exit(code=1)
    text = html
    if md:
        from markdownify import markdownify
        text = markdownify(html, heading_style="ATX")
    if out:
        out.write_text(text)
        console.print(f"[green]wrote[/] {out} ({out.stat().st_size} bytes)")
    else:
        console.print(text)


@posts_app.command("search")
def posts_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(20, "--limit", "-n"),
    pub: str | None = typer.Option(None, "--pub"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Search posts in a publication (yours unless --pub)."""
    with SubstackClient.create() as c:
        posts = c.search_posts(query=query, limit=limit, pub=pub)
    if json_out:
        console.print_json(data=posts)
        return
    t = Table(title=f"search: {query!r} (pub={pub or 'me'})")
    t.add_column("id", style="cyan", no_wrap=True)
    t.add_column("date", style="dim")
    t.add_column("title")
    for p in posts:
        t.add_row(
            str(p.get("id")),
            (p.get("post_date") or "")[:10],
            (p.get("title") or "")[:80],
        )
    console.print(t)


@posts_app.command("paywalled")
def posts_paywalled(
    post_id: str = typer.Argument(...),
    pub: str | None = typer.Option(None, "--pub"),
) -> None:
    """Print true/false: is this post paywalled?"""
    with SubstackClient.create() as c:
        console.print(str(c.is_post_paywalled(post_id, pub=pub)).lower())


@posts_app.command("get")
def posts_get(
    slug: str = typer.Option(..., "--slug", help="Post slug"),
    pub: str | None = typer.Option(None, "--pub"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Fetch a post by slug (postcli alias for `posts show`)."""
    with SubstackClient.create() as c:
        meta = c.get_post(slug, pub=pub)
    if json_out:
        console.print_json(data=meta)
        return
    console.print_json(data=meta)


@posts_app.command("react")
def posts_react(
    post_id: str = typer.Argument(...),
    reaction: str = typer.Option("❤", "--reaction", "-r"),
    off: bool = typer.Option(False, "--off", help="Unreact instead"),
    pub: str | None = typer.Option(None, "--pub"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """React (or --off to unreact) to a post."""
    from substack_ops.dedup import DedupDB, DuplicateActionError

    with SubstackClient.create() as c:
        action = "unreact_post" if off else "react_post"
        if not dry_run:
            try:
                DedupDB().check(target_id=str(post_id), action=action, force=force)
            except DuplicateActionError as exc:
                err_console.print(str(exc))
                raise typer.Exit(code=2) from exc
        r = c.react_to_post(
            post_id=post_id, reaction=reaction, on=not off, pub=pub, dry_run=dry_run
        )
        if not dry_run:
            DedupDB().record(target_id=str(post_id), action=action)
        _audit_write(action, target_id=str(post_id), payload=r, dry_run=dry_run)
    console.print_json(data=r)


@posts_app.command("restack")
def posts_restack(
    post_id: str = typer.Argument(...),
    off: bool = typer.Option(False, "--off"),
    pub: str | None = typer.Option(None, "--pub"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Restack (share) a post."""
    from substack_ops.dedup import DedupDB, DuplicateActionError

    with SubstackClient.create() as c:
        action = "unrestack_post" if off else "restack_post"
        if not dry_run:
            try:
                DedupDB().check(target_id=str(post_id), action=action, force=force)
            except DuplicateActionError as exc:
                err_console.print(str(exc))
                raise typer.Exit(code=2) from exc
        r = c.restack_post(post_id=post_id, on=not off, pub=pub, dry_run=dry_run)
        if not dry_run:
            DedupDB().record(target_id=str(post_id), action=action)
        _audit_write(action, target_id=str(post_id), payload=r, dry_run=dry_run)
    console.print_json(data=r)


# ---------------------------------------------------------------------------
# podcasts / recommendations / authors / categories / users / profile / feed
# ---------------------------------------------------------------------------

@podcasts_app.command("list")
def podcasts_list(
    limit: int = typer.Option(20, "--limit", "-n"),
    pub: str | None = typer.Option(None, "--pub"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List podcast posts."""
    with SubstackClient.create() as c:
        items = c.list_podcasts(limit=limit, pub=pub)
    if json_out:
        console.print_json(data=items)
        return
    t = Table(title=f"Podcasts (pub={pub or 'me'})")
    t.add_column("id", style="cyan")
    t.add_column("date", style="dim")
    t.add_column("title")
    for p in items:
        t.add_row(
            str(p.get("id")),
            (p.get("post_date") or "")[:10],
            (p.get("title") or "")[:80],
        )
    console.print(t)


@recs_app.command("list")
def recs_list(
    pub: str | None = typer.Option(None, "--pub"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show recommended publications."""
    with SubstackClient.create() as c:
        items = c.get_recommendations(pub=pub)
    if json_out:
        console.print_json(data=items)
        return
    for r in items:
        console.print(r.get("url", ""))


@authors_app.command("list")
def authors_list(
    pub: str | None = typer.Option(None, "--pub"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List authors of a publication."""
    with SubstackClient.create() as c:
        items = c.get_authors(pub=pub)
    if json_out:
        console.print_json(data=items)
        return
    t = Table(title=f"Authors (pub={pub or 'me'})")
    t.add_column("handle", style="cyan")
    t.add_column("name")
    t.add_column("role")
    for a in items:
        t.add_row(
            a.get("handle") or "",
            a.get("name") or a.get("display_name") or "",
            a.get("role") or "",
        )
    console.print(t)


@categories_app.command("list")
def categories_list(json_out: bool = typer.Option(False, "--json")) -> None:
    """List all top-level Substack categories."""
    with SubstackClient.create() as c:
        items = c.list_categories()
    if json_out:
        console.print_json(data=items)
        return
    t = Table()
    t.add_column("id", style="cyan")
    t.add_column("name")
    for cat in items:
        t.add_row(str(cat["id"]), cat["name"])
    console.print(t)


@categories_app.command("get")
def categories_get(
    name: str | None = typer.Option(None, "--name"),
    id: int | None = typer.Option(None, "--id"),
    limit: int = typer.Option(50, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Get publications in a category."""
    if not name and not id:
        err_console.print("Provide --name or --id")
        raise typer.Exit(code=2)
    with SubstackClient.create() as c:
        data = c.get_category(name=name, id=id)
    pubs = data["publications"][:limit]
    if json_out:
        console.print_json(data={"name": data["name"], "id": data["id"], "publications": pubs})
        return
    t = Table(title=f"Category {data['name']} ({data['id']}): {len(pubs)} pubs")
    t.add_column("id")
    t.add_column("subdomain")
    t.add_column("name")
    for p in pubs:
        t.add_row(str(p.get("id")), p.get("subdomain") or "", p.get("name") or "")
    console.print(t)


@users_app.command("get")
def users_get(
    handle: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Public profile by handle (auto-follows renamed handles)."""
    with SubstackClient.create() as c:
        data = c.get_profile(handle)
    if json_out:
        console.print_json(data=data)
        return
    console.print_json(data={k: data.get(k) for k in ("id", "name", "handle", "bio", "profile_set_up_at") if k in data})


@users_app.command("subscriptions")
def users_subscriptions(
    handle: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Subscriptions for a public profile."""
    with SubstackClient.create() as c:
        subs = c.get_subscriptions(handle)
    if json_out:
        console.print_json(data=subs)
        return
    t = Table(title=f"@{handle}: {len(subs)} subs")
    t.add_column("publication")
    t.add_column("domain")
    t.add_column("state")
    for s in subs:
        t.add_row(
            s.get("publication_name") or "",
            s.get("domain") or "",
            s.get("membership_state") or "",
        )
    console.print(t)


@profile_app.command("me")
def profile_me(json_out: bool = typer.Option(False, "--json")) -> None:
    """Your own profile."""
    with SubstackClient.create() as c:
        data = c.get_my_profile()
    if json_out:
        console.print_json(data=data)
        return
    t = Table(show_header=False, box=None)
    t.add_column(style="bold cyan")
    t.add_column()
    for k in ("user_id", "name", "handle", "publication_id", "subscriptions_count"):
        t.add_row(k, str(data.get(k) or ""))
    console.print(t)
    if data.get("publications"):
        t2 = Table(title="publications", show_header=True)
        t2.add_column("id")
        t2.add_column("name")
        t2.add_column("subdomain")
        for p in data["publications"]:
            t2.add_row(str(p.get("id") or ""), p.get("name") or "", p.get("subdomain") or "")
        console.print(t2)


@profile_app.command("get")
def profile_get(handle: str = typer.Argument(...)) -> None:
    """Alias for `users get`."""
    users_get(handle=handle, json_out=True)


@feed_app.command("list")
def feed_list(
    tab: str = typer.Option("for-you", "--tab", help="for-you | subscribed | category-{slug}"),
    limit: int = typer.Option(20, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Reader feed."""
    with SubstackClient.create() as c:
        items = c.get_feed(tab=tab, limit=limit)
    if json_out:
        console.print_json(data=items)
        return
    t = Table(title=f"Feed: {tab}")
    t.add_column("type", style="dim")
    t.add_column("id", style="cyan")
    t.add_column("body")
    for it in items:
        comment = it.get("comment") or {}
        body = (comment.get("body") or it.get("title") or "").replace("\n", " ")
        t.add_row(
            it.get("type") or "?",
            str(comment.get("id") or it.get("id") or ""),
            body[:90],
        )
    console.print(t)


def _audit_write(action: str, *, target_id: str, payload: dict[str, Any], dry_run: bool) -> None:
    """Write a single-action audit row (used by react/restack/delete commands)."""
    from substack_ops.reply_engine.base import audit_log

    audit_log(
        {
            "mode": action,
            "dry_run": dry_run,
            "target_id": target_id,
            "result_status": "dry_run" if dry_run else "posted",
            "payload": payload if dry_run else None,
        }
    )


# ---------------------------------------------------------------------------
# comments
# ---------------------------------------------------------------------------

def _walk_comments(node: dict[str, Any], tree: Tree) -> None:
    children = node.get("children") or node.get("replies") or []
    for ch in children:
        author = ch.get("name") or (ch.get("user") or {}).get("name") or "?"
        body = (ch.get("body") or "").replace("\n", " ").strip()
        cid = ch.get("id")
        label = f"[cyan]{author}[/] [dim]#{cid}[/]: {body[:140]}"
        sub = tree.add(label)
        _walk_comments(ch, sub)


@comments_app.command("tree")
def comments_tree(
    post_id: str = typer.Argument(..., help="Post id"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Pretty-print the comment tree for a post."""
    with SubstackClient.create() as c:
        data = c.get_comments(post_id)

    if json_out:
        console.print_json(data=data)
        return

    comments = data.get("comments") or []
    root = Tree(f"[bold]Post {post_id}[/] · {len(comments)} top-level comments")
    for top in comments:
        author = top.get("name") or (top.get("user") or {}).get("name") or "?"
        body = (top.get("body") or "").replace("\n", " ").strip()
        cid = top.get("id")
        node = root.add(f"[bold cyan]{author}[/] [dim]#{cid}[/]: {body[:140]}")
        _walk_comments(top, node)
    console.print(root)


@comments_app.command("export")
def comments_export(
    post_id: str = typer.Argument(...),
    out: Path = typer.Option(Path("comments.json"), "--out"),
    pub: str | None = typer.Option(None, "--pub"),
) -> None:
    """Export raw comments tree to JSON."""
    with SubstackClient.create() as c:
        data = c.get_comments(post_id, pub=pub)
    out.write_text(json.dumps(data, indent=2))
    console.print(f"[green]wrote[/] {out} ({out.stat().st_size} bytes)")


@comments_app.command("add")
def comments_add(
    post_id: str = typer.Argument(...),
    body: str = typer.Argument(..., help="Top-level comment body"),
    pub: str | None = typer.Option(None, "--pub"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Add a top-level comment on a post."""
    from substack_ops.dedup import DedupDB, DuplicateActionError

    target = f"post:{post_id}:top"
    with SubstackClient.create() as c:
        if not dry_run:
            try:
                DedupDB().check(target_id=target, action="add_comment", force=force)
            except DuplicateActionError as exc:
                err_console.print(str(exc))
                raise typer.Exit(code=2) from exc
        r = c.add_comment(post_id=post_id, body=body, pub=pub, dry_run=dry_run)
        if not dry_run:
            DedupDB().record(target_id=target, action="add_comment")
        _audit_write("add_comment", target_id=target, payload=r, dry_run=dry_run)
    console.print_json(data=r)


@comments_app.command("react")
def comments_react(
    comment_id: str = typer.Argument(...),
    reaction: str = typer.Option("❤", "--reaction", "-r"),
    kind: str = typer.Option("post", "--kind", help="post | note"),
    off: bool = typer.Option(False, "--off"),
    pub: str | None = typer.Option(None, "--pub"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """React to a comment (kind=post for post-comments, kind=note for note-replies)."""
    from substack_ops.dedup import DedupDB, DuplicateActionError

    action = "unreact_comment" if off else "react_comment"
    target = f"{kind}:{comment_id}"
    with SubstackClient.create() as c:
        if not dry_run:
            try:
                DedupDB().check(target_id=target, action=action, force=force)
            except DuplicateActionError as exc:
                err_console.print(str(exc))
                raise typer.Exit(code=2) from exc
        r = c.react_to_comment(
            comment_id=comment_id, kind=kind, reaction=reaction, on=not off,
            pub=pub, dry_run=dry_run,
        )
        if not dry_run:
            DedupDB().record(target_id=target, action=action)
        _audit_write(action, target_id=target, payload=r, dry_run=dry_run)
    console.print_json(data=r)


@comments_app.command("delete")
def comments_delete(
    comment_id: str = typer.Argument(...),
    kind: str = typer.Option("post", "--kind", help="post | note (different hosts!)"),
    pub: str | None = typer.Option(None, "--pub"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Delete a comment. post = pub host; note = substack.com."""
    from substack_ops.dedup import DedupDB, DuplicateActionError

    target = f"{kind}:{comment_id}"
    with SubstackClient.create() as c:
        if not dry_run:
            try:
                DedupDB().check(target_id=target, action="delete_comment", force=force)
            except DuplicateActionError as exc:
                err_console.print(str(exc))
                raise typer.Exit(code=2) from exc
        r = c.delete_comment(comment_id=comment_id, kind=kind, pub=pub, dry_run=dry_run)
        if not dry_run:
            DedupDB().record(target_id=target, action="delete_comment")
        _audit_write("delete_comment", target_id=target, payload=r, dry_run=dry_run)
    console.print_json(data=r)


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------

@notes_app.command("list")
def notes_list(
    limit: int = typer.Option(20, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List your notes."""
    with SubstackClient.create() as c:
        notes = c.list_notes(limit=limit)
    if json_out:
        console.print_json(data=notes)
        return

    t = Table(title=f"Notes (limit={limit})")
    t.add_column("id", style="cyan", no_wrap=True)
    t.add_column("date", style="dim")
    t.add_column("body")
    t.add_column("replies", justify="right")
    t.add_column("reactions", justify="right")
    for n in notes:
        ctx = n.get("context") or {}
        comment = n.get("comment") or {}
        body = (comment.get("body") or n.get("body") or "").replace("\n", " ")
        date = (comment.get("date") or n.get("date") or "")[:10]
        t.add_row(
            str(comment.get("id") or n.get("id")),
            date,
            body[:80],
            str(comment.get("reply_count") or 0),
            str(comment.get("reaction_count") or 0),
        )
    console.print(t)


@notes_app.command("publish")
def notes_publish(
    body: str = typer.Argument(..., help="Note body (plain text)"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Publish a top-level note."""
    with SubstackClient.create() as c:
        r = c.publish_note(body=body, dry_run=dry_run)
        _audit_write("publish_note", target_id="(self)", payload=r, dry_run=dry_run)
    console.print_json(data=r)


@notes_app.command("react")
def notes_react(
    note_id: str = typer.Argument(...),
    reaction: str = typer.Option("❤", "--reaction", "-r"),
    off: bool = typer.Option(False, "--off"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """React to a note."""
    from substack_ops.dedup import DedupDB, DuplicateActionError

    action = "unreact_note" if off else "react_note"
    with SubstackClient.create() as c:
        if not dry_run:
            try:
                DedupDB().check(target_id=str(note_id), action=action, force=force)
            except DuplicateActionError as exc:
                err_console.print(str(exc))
                raise typer.Exit(code=2) from exc
        r = c.react_to_note(note_id=note_id, reaction=reaction, on=not off, dry_run=dry_run)
        if not dry_run:
            DedupDB().record(target_id=str(note_id), action=action)
        _audit_write(action, target_id=str(note_id), payload=r, dry_run=dry_run)
    console.print_json(data=r)


@notes_app.command("restack")
def notes_restack(
    note_id: str = typer.Argument(...),
    off: bool = typer.Option(False, "--off"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Restack a note."""
    from substack_ops.dedup import DedupDB, DuplicateActionError

    action = "unrestack_note" if off else "restack_note"
    with SubstackClient.create() as c:
        if not dry_run:
            try:
                DedupDB().check(target_id=str(note_id), action=action, force=force)
            except DuplicateActionError as exc:
                err_console.print(str(exc))
                raise typer.Exit(code=2) from exc
        r = c.restack_note(note_id=note_id, on=not off, dry_run=dry_run)
        if not dry_run:
            DedupDB().record(target_id=str(note_id), action=action)
        _audit_write(action, target_id=str(note_id), payload=r, dry_run=dry_run)
    console.print_json(data=r)


@notes_app.command("show")
def notes_show(
    note_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show a single note + its thread."""
    with SubstackClient.create() as c:
        thread = c.get_note_thread(note_id)
    if json_out:
        console.print_json(data=thread)
        return

    item = thread.get("item") or thread
    comment = item.get("comment") or item
    console.print(f"[bold]Note {comment.get('id')}[/]")
    console.print(comment.get("body", ""))
    console.print()
    children = comment.get("children") or item.get("children") or []
    if not children:
        console.print("[dim]no replies[/]")
        return
    root = Tree("Replies")
    for ch in children:
        author = ch.get("name") or (ch.get("user") or {}).get("name") or "?"
        body = (ch.get("body") or "").replace("\n", " ")
        node = root.add(f"[cyan]{author}[/] [dim]#{ch.get('id')}[/]: {body[:140]}")
        _walk_comments(ch, node)
    console.print(root)


# ---------------------------------------------------------------------------
# reply
# ---------------------------------------------------------------------------

@reply_app.command("template")
def reply_template_cmd(
    post_id: str = typer.Argument(...),
    template: str = typer.Option("thanks", "--template", "-t"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Default ON"),
    rate: float = typer.Option(30.0, "--rate", help="Min seconds between posts"),
) -> None:
    """Reply to comments using YAML template rules."""
    from substack_ops.reply_engine.template import run_template
    results = run_template(
        post_id=post_id,
        template_name=template,
        dry_run=dry_run,
        rate_seconds=rate,
    )
    _summarize(results, dry_run=dry_run, mode="template")


@reply_app.command("review")
def reply_review_cmd(
    post_id: str = typer.Argument(...),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    rate: float = typer.Option(30.0, "--rate"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Interactive: AI drafts, you accept/edit/skip/quit per comment.

    Uses host CLI (claude/cursor-agent/codex) on PATH for drafts.
    For a no-setup flow, use MCP propose_reply/confirm_reply from your chat app.
    """
    from substack_ops.reply_engine.ai_review import run_review
    results = run_review(
        post_id=post_id, dry_run=dry_run, rate_seconds=rate, model=model
    )
    _summarize(results, dry_run=dry_run, mode="ai_review")


@reply_app.command("bulk")
def reply_bulk_cmd(
    post_id: str = typer.Argument(...),
    out: Path = typer.Option(Path("drafts.json"), "--out"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Generate AI drafts for every POST comment into drafts.json.

    Uses host CLI (claude/cursor-agent/codex) on PATH for drafts.
    """
    from substack_ops.reply_engine.ai_bulk import generate_drafts
    n = generate_drafts(post_id=post_id, out=out, model=model)
    console.print(f"[green]wrote[/] {n} drafts to {out}")
    console.print(
        f"[dim]Edit {out}, change 'pending' -> 'approved' for replies you want, "
        f"then: substack-ops reply bulk-send {out}[/]"
    )


@reply_app.command("note-bulk")
def reply_note_bulk_cmd(
    note_id: str = typer.Argument(...),
    out: Path = typer.Option(Path("note-drafts.json"), "--out"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Generate AI drafts for every reply on a NOTE into drafts.json.

    Uses host CLI (claude/cursor-agent/codex) on PATH for drafts.
    """
    from substack_ops.reply_engine.ai_bulk import generate_note_drafts
    n = generate_note_drafts(note_id=note_id, out=out, model=model)
    console.print(f"[green]wrote[/] {n} drafts to {out}")
    console.print(
        f"[dim]Edit {out}, change 'pending' -> 'approved' for replies you want, "
        f"then: substack-ops reply bulk-send {out}[/]"
    )


@reply_app.command("bulk-send")
def reply_bulk_send_cmd(
    drafts_path: Path = typer.Argument(...),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    rate: float = typer.Option(30.0, "--rate"),
) -> None:
    """Post only drafts marked action: 'approved'."""
    from substack_ops.reply_engine.ai_bulk import send_drafts
    counts = send_drafts(drafts_path=drafts_path, dry_run=dry_run, rate_seconds=rate)
    t = Table(show_header=False, title=f"bulk-send {drafts_path}")
    t.add_column(style="bold cyan")
    t.add_column()
    for k, v in counts.items():
        t.add_row(k, str(v))
    console.print(t)


@reply_app.command("auto")
def reply_auto_cmd(
    post_id: str = typer.Argument(...),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    rate: float = typer.Option(30.0, "--rate"),
    model: str | None = typer.Option(None, "--model"),
    yes_i_mean_it: bool = typer.Option(
        False, "--yes-i-mean-it", help="Required to actually post AI replies"
    ),
) -> None:
    """Fully automated AI replies. Hard-gated."""
    if not dry_run and not yes_i_mean_it:
        err_console.print(
            "Refusing to live-post in auto mode without --yes-i-mean-it. "
            "Run with --dry-run first to preview."
        )
        raise typer.Exit(code=2)
    from substack_ops.reply_engine.ai_auto import run_auto
    results = run_auto(
        post_id=post_id, dry_run=dry_run, rate_seconds=rate, model=model
    )
    _summarize(results, dry_run=dry_run, mode="ai_auto")


# ---------------------------------------------------------------------------
# audit / auto / mcp / tui / quickstart
# ---------------------------------------------------------------------------

@audit_app.command("search")
def audit_search(
    kind: str | None = typer.Option(None, "--kind", help="Filter by mode prefix (e.g. note, react, ai_bulk)"),
    target: str | None = typer.Option(None, "--target", help="Substring of target_id"),
    status: str | None = typer.Option(None, "--status", help="dry_run | posted | orphaned"),
    since: str | None = typer.Option(None, "--since", help="e.g. 7d, 24h, 30m"),
    limit: int = typer.Option(50, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Search the audit log."""
    from substack_ops.audit import search_audit

    rows = search_audit(kind=kind, target=target, status=status, since=since, limit=limit)
    if json_out:
        console.print_json(data=rows)
        return
    if not rows:
        console.print("[dim]no matching rows[/]")
        return
    t = Table(title=f"audit ({len(rows)} rows)")
    t.add_column("ts", style="dim")
    t.add_column("mode", style="cyan")
    t.add_column("status")
    t.add_column("target")
    t.add_column("body")
    for r in rows:
        t.add_row(
            (r.get("ts") or "")[:19],
            (r.get("mode") or "")[:30],
            r.get("result_status") or "",
            str(r.get("target_id") or r.get("note_id") or r.get("post_id") or "")[:24],
            (r.get("reply_body") or "")[:60],
        )
    console.print(t)


@audit_app.command("dedup-status")
def audit_dedup_status(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show dedup DB stats."""
    from substack_ops.dedup import DedupDB

    stats = DedupDB().status()
    if json_out:
        console.print_json(data=stats)
        return
    t = Table(title="dedup DB")
    t.add_column("action", style="cyan")
    t.add_column("count", justify="right")
    for action, n in stats["actions"].items():
        t.add_row(action, str(n))
    t.add_row("[bold]total[/]", str(stats["total"]))
    console.print(t)


@auto_app.command("presets")
def auto_presets(json_out: bool = typer.Option(False, "--json")) -> None:
    """List built-in automation presets."""
    from substack_ops.auto.engine import list_presets

    items = list_presets()
    if json_out:
        console.print_json(data=items)
        return
    t = Table(title="presets")
    t.add_column("name", style="cyan")
    t.add_column("trigger")
    t.add_column("action")
    for p in items:
        t.add_row(p["name"], p["trigger"], p["action"])
    console.print(t)


@auto_app.command("run")
def auto_run(
    name: str = typer.Argument(..., help="Preset name (or path to YAML rule)"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Run one automation cycle."""
    from substack_ops.auto.engine import run_once

    counts = run_once(name=name, dry_run=dry_run, limit=limit)
    t = Table(title=f"auto run: {name}", show_header=False)
    t.add_column(style="cyan")
    t.add_column()
    for k, v in counts.items():
        t.add_row(k, str(v))
    console.print(t)


@auto_app.command("daemon")
def auto_daemon(
    name: str = typer.Argument(..., help="Preset to loop"),
    interval: int = typer.Option(60, "--interval", help="Seconds between cycles"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Loop a preset with --interval seconds between cycles. Ctrl-C to stop."""
    from substack_ops.auto.engine import run_daemon

    run_daemon(name=name, interval=interval, dry_run=dry_run)


mcp_app = typer.Typer(
    no_args_is_help=False,
    invoke_without_command=True,
    help="MCP server (run / install / list-tools)",
)
app.add_typer(mcp_app, name="mcp")


@mcp_app.callback()
def mcp_default(
    ctx: typer.Context,
    list_tools: bool = typer.Option(False, "--list-tools", help="Print tool names and exit"),
) -> None:
    """Default: run the stdio server. Use subcommands for install/serve."""
    if ctx.invoked_subcommand is not None:
        return
    from substack_ops.mcp.server import list_tool_names, serve

    if list_tools:
        for n in list_tool_names():
            console.print(n)
        return
    serve()


@mcp_app.command("serve")
def mcp_serve_cmd() -> None:
    """Run the stdio server (explicit form)."""
    from substack_ops.mcp.server import serve

    serve()


@mcp_app.command("list-tools")
def mcp_list_tools_cmd() -> None:
    """Print all MCP tool names."""
    from substack_ops.mcp.server import list_tool_names

    for n in list_tool_names():
        console.print(n)


@mcp_app.command("install")
def mcp_install_cmd(
    host: str = typer.Argument(
        ...,
        help="cursor | claude-desktop | claude-code | codex | print",
    ),
    name: str = typer.Option("substack-ops", "--name", help="Server name in host config"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print config, don't write"),
) -> None:
    """Add substack-ops to an MCP host's config file. Idempotent + backed up."""
    from substack_ops.mcp.install import install_to_host

    info = install_to_host(host=host, name=name, dry_run=dry_run)
    t = Table(show_header=False, title=f"mcp install -> {host}")
    t.add_column(style="bold cyan")
    t.add_column()
    for k, v in info.items():
        t.add_row(k, str(v))
    console.print(t)


@app.command("tui")
def tui_cmd() -> None:
    """Launch the interactive Textual TUI."""
    try:
        from substack_ops.tui.app import run as tui_run
    except ImportError as exc:
        err_console.print(f"TUI deps missing — `uv pip install textual`: {exc}")
        raise typer.Exit(code=2) from exc
    tui_run()


@app.command("quickstart")
def quickstart() -> None:
    """Print a curated quickstart tour."""
    console.print(
        """[bold cyan]substack-ops quickstart[/]

1. Verify auth:           [green]substack-ops auth verify[/]
2. List your posts:       [green]substack-ops posts list[/]
3. Show a post:           [green]substack-ops posts show <id>[/]
4. Read body (markdown):  [green]substack-ops posts content <id> --md[/]
5. Search any pub:        [green]substack-ops posts search "ai" --pub stratechery[/]
6. List your notes:       [green]substack-ops notes list[/]
7. Comments tree:         [green]substack-ops comments tree <post_id>[/]
8. Bulk-draft replies:    [green]substack-ops reply bulk <post_id> --out drafts.json[/]
   then edit drafts.json (pending → approved) and:
                          [green]substack-ops reply bulk-send drafts.json --no-dry-run[/]
9. Reactions:             [green]substack-ops posts react <id>[/] / [green]notes react <id>[/]
10. Restack:              [green]substack-ops posts restack <id>[/] / [green]notes restack <id>[/]
11. Reader feed:          [green]substack-ops feed list --tab subscribed[/]
12. Recommendations:      [green]substack-ops recommendations list --pub stratechery[/]
13. Profile:              [green]substack-ops profile me[/] / [green]users get <handle>[/]
14. Categories:           [green]substack-ops categories list[/]
15. Audit log:            [green]substack-ops audit search --since 24h[/]
16. Dedup DB status:      [green]substack-ops audit dedup-status[/]
17. Auto presets:         [green]substack-ops auto presets[/]
18. MCP server:           [green]substack-ops mcp[/]
19. Textual TUI:          [green]substack-ops tui[/]
20. Auth Chrome cookies:  [green]substack-ops auth login[/] (M8)
"""
    )


def _summarize(results: list[dict[str, Any]], *, dry_run: bool, mode: str) -> None:
    n = len(results)
    if not n:
        console.print(f"[dim]{mode}: no comments matched[/]")
        return
    label = "would post" if dry_run else "posted"
    console.print(f"[green]{mode}[/]: {label} {n} replies")
    for r in results[:10]:
        cid = r.get("comment_id")
        body = r.get("reply") or r.get("draft") or ""
        console.print(f"  [cyan]#{cid}[/] -> {body[:120]}")
    if n > 10:
        console.print(f"  [dim]... and {n - 10} more[/]")


def main() -> None:  # convenience for `python -m substack_ops.cli`
    app()


if __name__ == "__main__":
    main()
