"""Extended Substack client (standalone, no NHagar/postcli runtime dep).

Wraps vendored `Newsletter` / `Post` and adds every endpoint we need:
- post reads (list/show/content/search/paywalled/podcasts)
- post writes (react/restack/comment)
- comment reads + writes + delete (host-aware)
- note reads (list/thread/replies) + writes (publish/reply/react/restack)
- recommendations / authors / categories / users / profile / feed
- multi-publication via per-call `pub` override

All HTTP goes through `httpx.Client` reusing cookies from auth.py.
Write operations route through `dedup.py` and `audit.py` (M4).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from substack_ops._substack import Newsletter, Post, SubstackAuth
from substack_ops.auth import SubstackConfig, get_authed_session

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)

SUBSTACK = "https://substack.com"


def _normalize_pub_url(pub: str) -> str:
    """`foo` -> `https://foo.substack.com`, `foo.example.com` -> `https://foo.example.com`."""
    if pub.startswith("http://") or pub.startswith("https://"):
        return pub.rstrip("/")
    if "." in pub:
        return f"https://{pub}".rstrip("/")
    return f"https://{pub}.substack.com"


@dataclass
class SubstackClient:
    cfg: SubstackConfig
    auth: SubstackAuth
    http: httpx.Client

    @classmethod
    def create(cls) -> SubstackClient:
        auth, cfg = get_authed_session()
        cookies = {
            "substack.sid": cfg.session_token_decoded,
            "substack.lli": "1",
        }
        http = httpx.Client(
            timeout=30,
            follow_redirects=True,
            cookies=cookies,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Origin": cfg.publication_url,
                "Referer": cfg.publication_url + "/",
            },
        )
        return cls(cfg=cfg, auth=auth, http=http)

    def pub_url(self, pub: str | None = None) -> str:
        """Resolve target publication URL (own pub if `pub` is None)."""
        if not pub:
            return self.cfg.publication_url
        return _normalize_pub_url(pub)

    def pub_host(self, pub: str | None = None) -> str:
        return urlparse(self.pub_url(pub)).netloc

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> SubstackClient:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def newsletter(self, pub: str | None = None) -> Newsletter:
        return Newsletter(self.pub_url(pub), auth=self.auth)

    def list_posts(
        self,
        limit: int | None = None,
        sorting: str = "new",
        pub: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return raw post dicts."""
        n = self.newsletter(pub=pub)
        return n._fetch_paginated_posts({"sort": sorting}, limit=limit)

    def search_posts(
        self,
        query: str,
        limit: int | None = None,
        pub: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.newsletter(pub=pub).search_posts(query=query, limit=limit)

    def list_podcasts(
        self,
        limit: int | None = None,
        pub: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.newsletter(pub=pub).get_podcasts(limit=limit)

    def get_recommendations(self, pub: str | None = None) -> list[dict[str, Any]]:
        recs = self.newsletter(pub=pub).get_recommendations()
        return [{"url": r.url} for r in recs]

    def get_authors(self, pub: str | None = None) -> list[dict[str, Any]]:
        return self.newsletter(pub=pub).get_authors()

    def get_post(
        self, post_id: int | str, pub: str | None = None
    ) -> dict[str, Any]:
        """Get a post by numeric id OR slug. Returns full metadata."""
        base = self.pub_url(pub)
        if isinstance(post_id, int) or str(post_id).isdigit():
            url = f"{base}/api/v1/posts/by-id/{post_id}"
            r = self.http.get(url)
            if r.status_code == 200:
                data = r.json()
                return data.get("post", data)
        slug_url = f"{base}/p/{post_id}"
        return Post(slug_url, auth=self.auth).get_metadata()

    def get_post_content(
        self, post_id: int | str, pub: str | None = None
    ) -> str | None:
        """Return body_html for a post (auth-aware for paywalled)."""
        meta = self.get_post(post_id, pub=pub)
        return meta.get("body_html")

    def is_post_paywalled(
        self, post_id: int | str, pub: str | None = None
    ) -> bool:
        return self.get_post(post_id, pub=pub).get("audience") == "only_paid"

    def get_post_stats(self, post_id: int | str) -> dict[str, Any]:
        """Stats for a single post.

        Substack's full email/open/click stats live behind a dashboard CSRF flow
        we don't yet replicate (M3 task). For now, surface the counts that are
        baked into post metadata: comments, reactions, restacks, audience.
        Falls back gracefully and includes which endpoints we tried.
        """
        # First try premium dashboard endpoints (probably 403/404, but harmless).
        privileged = [
            f"{self.cfg.publication_url}/api/v1/post-management/posts/{post_id}/stats",
            f"{self.cfg.publication_url}/api/v1/admin/posts/{post_id}/stats",
        ]
        attempts: list[dict[str, Any]] = []
        for url in privileged:
            r = self.http.get(url)
            attempts.append({"url": url, "status": r.status_code})
            if r.status_code == 200:
                try:
                    return {"_endpoint": url, **r.json()}
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.3)

        # Fallback: pull baked-in counts from post metadata.
        meta = self.get_post(post_id)
        keep = {
            "id", "title", "audience", "post_date", "type",
            "comment_count", "reaction_count", "restacks", "wordcount",
            "reactions", "video_view_count", "audio_listen_count",
        }
        return {
            "_source": "post-metadata",
            "_note": "Full email/open/click stats require dashboard CSRF (M3 TODO).",
            "_attempts": attempts,
            **{k: meta[k] for k in keep if k in meta},
        }

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def get_comments(
        self, post_id: int | str, pub: str | None = None
    ) -> dict[str, Any]:
        """Fetch the full comment tree for a post."""
        base = self.pub_url(pub)
        url = (
            f"{base}/api/v1/post/{post_id}/comments"
            "?all_comments=true&sort=best_first"
        )
        r = self.http.get(url)
        r.raise_for_status()
        return r.json()

    def post_comment_reply(
        self,
        post_id: int | str,
        body: str,
        parent_id: int | None = None,
        *,
        dry_run: bool = True,
        pub: str | None = None,
    ) -> dict[str, Any]:
        """Reply to a post or to a parent comment.

        If `parent_id` is None, this becomes a top-level comment on the post.
        """
        base = self.pub_url(pub)
        url = f"{base}/api/v1/post/{post_id}/comment"
        payload: dict[str, Any] = {"body": body}
        if parent_id is not None:
            payload["parent_id"] = int(parent_id)
        if dry_run:
            return {"_dry_run": True, "url": url, "payload": payload}
        r = self.http.post(url, json=payload)
        r.raise_for_status()
        return r.json()

    def add_comment(
        self,
        post_id: int | str,
        body: str,
        *,
        dry_run: bool = True,
        pub: str | None = None,
    ) -> dict[str, Any]:
        """Top-level comment on a post (parent_id=None)."""
        return self.post_comment_reply(
            post_id=post_id,
            body=body,
            parent_id=None,
            dry_run=dry_run,
            pub=pub,
        )

    def delete_comment(
        self,
        comment_id: int | str,
        *,
        kind: str = "post",
        pub: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Delete a comment. `kind` is "post" (uses pub host) or "note" (uses substack.com).

        Bug log: post-comment delete needs publication host; note delete uses
        bare substack.com. Different hosts for the same verb.
        """
        if kind == "post":
            url = f"{self.pub_url(pub)}/api/v1/comment/{comment_id}"
        elif kind == "note":
            url = f"{SUBSTACK}/api/v1/comment/{comment_id}"
        else:
            raise ValueError(f"kind must be 'post' or 'note', got {kind!r}")
        if dry_run:
            return {"_dry_run": True, "method": "DELETE", "url": url}
        r = self.http.delete(url)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code}

    def react_to_comment(
        self,
        comment_id: int | str,
        *,
        kind: str = "post",
        reaction: str = "❤",
        on: bool = True,
        pub: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """React (or unreact when on=False) to a comment / note.

        Endpoint pattern (discovered): POST/DELETE
        {host}/api/v1/comment/{id}/reaction with {"reaction": "..."}
        """
        host = self.pub_url(pub) if kind == "post" else SUBSTACK
        url = f"{host}/api/v1/comment/{comment_id}/reaction"
        payload = {"reaction": reaction}
        if dry_run:
            return {
                "_dry_run": True,
                "method": "POST" if on else "DELETE",
                "url": url,
                "payload": payload,
            }
        r = self.http.post(url, json=payload) if on else self.http.delete(url, params=payload)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code}

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def list_notes(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Fetch notes authored by the current user."""
        url = f"https://substack.com/api/v1/reader/feed/profile/{self.cfg.user_id}"
        r = self.http.get(url)
        r.raise_for_status()
        items = r.json().get("items") or r.json().get("posts") or []
        # Filter to actual notes vs reposts/cross-posts.
        notes = [it for it in items if it.get("type") in ("comment", "feed")]
        return notes[:limit] if limit else notes

    def get_note_thread(self, note_id: int | str) -> dict[str, Any]:
        """Fetch the note item itself (no replies)."""
        url = f"https://substack.com/api/v1/reader/comment/{note_id}"
        r = self.http.get(url)
        r.raise_for_status()
        return r.json()

    def get_note_replies(
        self,
        note_id: int | str,
        *,
        paginate: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch all top-level replies (with their descendantComments) for a note.

        Endpoint: /api/v1/reader/comment/{id}/replies
        Returns: list of comment dicts with `children` populated from
                 `descendantComments`, normalized to the same shape as the
                 post-comments tree so `walk_comments` works on both.
        """
        cursor: str | None = None
        out: list[dict[str, Any]] = []
        seen = 0
        while True:
            url = f"https://substack.com/api/v1/reader/comment/{note_id}/replies"
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            r = self.http.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            for branch in data.get("commentBranches") or []:
                comment = dict(branch.get("comment") or {})
                # Normalize: copy descendantComments -> children (recursively flat-ish).
                comment["children"] = _normalize_descendants(
                    branch.get("descendantComments") or []
                )
                out.append(comment)
                seen += 1
            cursor = data.get("nextCursor")
            if not paginate or not cursor or not (data.get("commentBranches") or []):
                break
            time.sleep(0.4)
        return out

    def post_note_reply(
        self,
        note_id: int | str,
        body: str,
        *,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Reply to a note (notes are stored as root comments).

        Bug log: payload field is `parent_id`, NOT `parent_comment_id`. Substack
        silently drops the wrong field and creates a top-level note.
        """
        url = f"{SUBSTACK}/api/v1/comment/feed"
        payload = {"bodyJson": _doc_from_text(body), "parent_id": int(note_id)}
        if dry_run:
            return {"_dry_run": True, "url": url, "payload": payload}
        r = self.http.post(url, json=payload)
        r.raise_for_status()
        return r.json()

    def publish_note(
        self,
        body: str,
        *,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Publish a top-level note (no parent_id)."""
        url = f"{SUBSTACK}/api/v1/comment/feed"
        payload: dict[str, Any] = {"bodyJson": _doc_from_text(body)}
        if dry_run:
            return {"_dry_run": True, "url": url, "payload": payload}
        r = self.http.post(url, json=payload)
        r.raise_for_status()
        return r.json()

    def react_to_note(
        self,
        note_id: int | str,
        *,
        reaction: str = "❤",
        on: bool = True,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return self.react_to_comment(
            comment_id=note_id, kind="note", reaction=reaction, on=on, dry_run=dry_run
        )

    def restack_note(
        self,
        note_id: int | str,
        *,
        on: bool = True,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        url = f"{SUBSTACK}/api/v1/restack/feed"
        payload = {
            "postId": None,
            "commentId": int(note_id),
            "tabId": "for-you",
            "surface": "feed",
        }
        if dry_run:
            return {
                "_dry_run": True,
                "method": "POST" if on else "DELETE",
                "url": url,
                "payload": payload,
            }
        r = self.http.post(url, json=payload) if on else self.http.delete(
            url, params=payload
        )
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code}

    # ------------------------------------------------------------------
    # Posts: engagement
    # ------------------------------------------------------------------

    def react_to_post(
        self,
        post_id: int | str,
        *,
        reaction: str = "❤",
        on: bool = True,
        pub: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        url = f"{self.pub_url(pub)}/api/v1/post/{post_id}/reaction"
        payload = {"reaction": reaction}
        if dry_run:
            return {
                "_dry_run": True,
                "method": "POST" if on else "DELETE",
                "url": url,
                "payload": payload,
            }
        r = self.http.post(url, json=payload) if on else self.http.delete(
            url, params=payload
        )
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code}

    def restack_post(
        self,
        post_id: int | str,
        *,
        on: bool = True,
        pub: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        url = f"{SUBSTACK}/api/v1/restack/feed"
        payload = {
            "postId": int(post_id),
            "commentId": None,
            "tabId": "for-you",
            "surface": "feed",
        }
        if dry_run:
            return {
                "_dry_run": True,
                "method": "POST" if on else "DELETE",
                "url": url,
                "payload": payload,
            }
        r = self.http.post(url, json=payload) if on else self.http.delete(
            url, params=payload
        )
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code}

    # ------------------------------------------------------------------
    # Profile / users / feed / categories
    # ------------------------------------------------------------------

    def get_my_profile(self) -> dict[str, Any]:
        """`/api/v1/subscriptions` is the closest thing to "me"."""
        r = self.http.get(f"{SUBSTACK}/api/v1/subscriptions")
        r.raise_for_status()
        data = r.json()
        pub_users = data.get("publicationUsers") or []
        publications = data.get("publications") or []
        me = pub_users[0] if pub_users else {}
        return {
            "user_id": self.cfg.user_id,
            "name": me.get("name"),
            "handle": me.get("twitter_screen_name") or me.get("name"),
            "publication_id": me.get("publication_id"),
            "publications": [
                {"id": p.get("id"), "name": p.get("name"), "subdomain": p.get("subdomain")}
                for p in publications
            ],
            "subscriptions_count": len(data.get("subscriptions") or []),
        }

    def get_profile(self, handle: str) -> dict[str, Any]:
        """Get any user's public profile by handle (with redirect)."""
        from substack_ops._substack import User

        u = User(handle, follow_redirects=True)
        return u.get_raw_data()

    def get_subscriptions(self, handle: str) -> list[dict[str, Any]]:
        from substack_ops._substack import User

        return User(handle, follow_redirects=True).get_subscriptions()

    def get_feed(
        self,
        tab: str = "for-you",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Reader feed.

        tab: for-you | recommended | subscribed | home | category-<id-or-slug>.
        Endpoint: GET /api/v1/reader/feed?tab=<tab>.
        """
        # Normalize tab name. The server accepts the literal `tab` query.
        # For categories we accept `category-<n>` and pass through as-is.
        url = f"{SUBSTACK}/api/v1/reader/feed?tab={tab}"
        r = self.http.get(url)
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or data.get("posts") or data
        if isinstance(items, dict):
            items = items.get("items") or []
        items = list(items)
        return items[:limit] if limit else items

    def list_categories(self) -> list[dict[str, Any]]:
        from substack_ops._substack import list_all_categories

        return [{"name": n, "id": i} for n, i in list_all_categories()]

    def get_category(self, name: str | None = None, id: int | None = None) -> dict[str, Any]:
        from substack_ops._substack import Category

        c = Category(name=name, id=id)
        pubs = c.get_publications()
        return {"name": c.name, "id": c.id, "publications": pubs}


def _doc_from_text(text: str) -> dict[str, Any]:
    """Build the bodyJson doc that /api/v1/comment/feed expects."""
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _normalize_descendants(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Substack returns descendantComments as a flat list, sometimes wrapped
    as `{type: "comment", comment: {...}}`. We unwrap and rebuild the tree
    by ancestor_path so `walk_comments` works uniformly.
    """
    by_id: dict[int, dict[str, Any]] = {}
    for it in items:
        # Unwrap envelope if needed.
        comment = it.get("comment") if isinstance(it.get("comment"), dict) else it
        if not comment or "id" not in comment:
            continue
        c = dict(comment)
        c["children"] = []
        by_id[c["id"]] = c

    roots: list[dict[str, Any]] = []
    for c in by_id.values():
        path = (c.get("ancestor_path") or "").strip(".")
        parent_id: int | None = None
        if path:
            parts = [p for p in path.split(".") if p.isdigit()]
            if parts:
                parent_id = int(parts[-1])
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(c)
        else:
            roots.append(c)
    return roots
