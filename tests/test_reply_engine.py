"""Reply engine: walk_comments, RateLimiter, template matching."""

from __future__ import annotations

import time

from substack_ops.reply_engine.base import RateLimiter, walk_comments
from substack_ops.reply_engine.template import pick_reply


def test_walk_comments_yields_nested_with_depth():
    tree = [
        {
            "id": 1,
            "name": "alice",
            "user_id": 100,
            "body": "great post",
            "children": [
                {"id": 2, "name": "bob", "user_id": 101, "body": "agreed", "children": []},
                {
                    "id": 3,
                    "name": "carol",
                    "user_id": 102,
                    "body": "thanks",
                    "children": [
                        {"id": 4, "name": "dave", "user_id": 103, "body": "yep"},
                    ],
                },
            ],
        }
    ]
    refs = list(walk_comments(post_id=999, comments=tree))
    assert [r.comment_id for r in refs] == [1, 2, 3, 4]
    assert [r.depth for r in refs] == [0, 1, 1, 2]
    assert refs[1].parent_id == 1
    assert refs[3].parent_id == 3


def test_walk_comments_skips_self():
    tree = [
        {"id": 1, "user_id": 999, "body": "mine"},
        {"id": 2, "user_id": 100, "body": "theirs"},
    ]
    refs = list(walk_comments(post_id=1, comments=tree, skip_self_id=999))
    assert [r.comment_id for r in refs] == [2]


def test_rate_limiter_enforces_min_gap():
    rl = RateLimiter(seconds=0.1, jitter=0.0)
    rl.wait()
    t0 = time.monotonic()
    rl.wait()
    assert time.monotonic() - t0 >= 0.09


def test_pick_reply_matches_keyword():
    rules = [
        {"name": "thanks", "match": {"any": ["thank"]}, "replies": ["You bet"]},
        {"name": "default", "match": {"any": ["*"]}, "replies": ["catchall"]},
    ]
    assert pick_reply(rules, "Thanks for this!") == ("thanks", "You bet")
    assert pick_reply(rules, "no match here") == ("default", "catchall")


def test_pick_reply_returns_none_when_no_rules():
    assert pick_reply([], "anything") is None
