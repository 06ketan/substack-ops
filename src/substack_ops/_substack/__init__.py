"""Vendored minimum from NHagar/substack_api (MIT-licensed).

Re-implemented against httpx to drop the `requests` runtime dep and to give us
a single Cookie/User-Agent surface. Public surface kept compatible with how
upstream is used elsewhere in this codebase.
"""

from __future__ import annotations

from substack_ops._substack.auth import SubstackAuth
from substack_ops._substack.category import Category, list_all_categories
from substack_ops._substack.newsletter import Newsletter
from substack_ops._substack.post import Post
from substack_ops._substack.user import User, resolve_handle_redirect

__all__ = [
    "Category",
    "Newsletter",
    "Post",
    "SubstackAuth",
    "User",
    "list_all_categories",
    "resolve_handle_redirect",
]
