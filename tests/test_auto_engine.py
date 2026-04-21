"""Automation engine: preset loader + rule resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from substack_ops.auto.engine import _load_rule, list_presets


def test_list_presets_has_4_builtins():
    presets = list_presets()
    names = {p["name"] for p in presets}
    assert {"like-back", "auto-reply", "auto-restack", "follow-back"}.issubset(names)


def test_load_rule_by_name():
    rule = _load_rule("like-back")
    assert rule["trigger"] == "note_liked_by"
    assert rule["action"] == "react_to_their_latest_note"


def test_load_rule_unknown_raises():
    with pytest.raises(ValueError):
        _load_rule("does-not-exist")


def test_load_rule_from_yaml_file(tmp_path: Path):
    rule_file = tmp_path / "custom.yaml"
    rule_file.write_text(
        "name: my-rule\ntrigger: note_liked_by\naction: react_to_their_latest_note\n"
    )
    rule = _load_rule(str(rule_file))
    assert rule["name"] == "my-rule"
