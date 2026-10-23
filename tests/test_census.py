"""Unit tests for the Natro census taxonomy.

The census tool is a triage instrument: a misclassified hit sends the next
agent after the wrong feature.  These tests pin the verdicts for the
categories that dominated the first full run (settings, language gaps,
case-insensitive cross-file calls) and the worker deadline path.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest


def _load_census():
    path = Path(__file__).resolve().parents[1] / "tools" / "natro_census.py"
    spec = importlib.util.spec_from_file_location("natro_census", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


census = _load_census()


def test_classify_setting_before_command_regex():
    kind, name, _ = census.classify_log(
        "setting DetectHiddenWindows 0 (noted, linux no-op)")
    assert (kind, name) == ("setting", "DetectHiddenWindows")


def test_classify_hash_directive_setting():
    kind, name, _ = census.classify_log(
        "setting #SingleInstance Force (noted, linux no-op)")
    assert (kind, name) == ("setting", "#SingleInstance")


def test_classify_sleep_legacy_stays_visible():
    # Sleep(100) is currently misparsed as a legacy command.  It must not be
    # swallowed as a benign setting; the parser fix is tracked separately.
    kind, name, _ = census.classify_log(
        "Sleep (100) (OS/window op, linux no-op)")
    assert (kind, name) == ("command", "Sleep")


def test_classify_language_gaps():
    assert census.classify_log(
        "for: unsupported enumerable 'bitmaps[time]' (skipped)")[0] == "for"
    assert census.classify_log(
        "assign-target 'settings[\"x\"]' has no live container (logged)")[0] \
        == "assign-target"
    assert census.classify_log(
        "method .rawread() unsupported (logged)")[0] == "method"


def test_setting_is_not_load_bearing():
    assert census.verdict_for("DetectHiddenWindows", "setting") == "setting-noop"
    assert census.load_bearing_for("setting-noop") is False


def test_language_gap_is_load_bearing_but_known():
    assert census.verdict_for("for-in", "for") == "language-gap"
    assert census.load_bearing_for("language-gap") is True


def test_com_surface_keeps_a_known_gap_verdict():
    for name in ("ComValue", "ComObjGet", "ComCall"):
        assert census.verdict_for(name, "builtin") in (
            "windows-only", "external-service")


def test_unmodeled_dllcall_is_classified_and_visible():
    kind, name, _ = census.classify_log(
        "DllCall Shell32\\SHEvaluateSystemCommandTemplate: Windows ABI "
        "not modeled on Linux (returns 0; logged)")
    assert (kind, name) == ("dllcall",
                            "Shell32\\SHEvaluateSystemCommandTemplate")
    assert census.verdict_for(name, kind) == "windows-only"
    # A display-only no-op still stays visible in the report.
    kind, name, _ = census.classify_log(
        "DllCall DeleteObject: display-only/no-op on Linux (logged)")
    assert kind == "dllcall" and name == "DeleteObject"
    assert census.verdict_for(name, kind) == "windows-only"


def test_aggregate_is_case_insensitive_for_cross_file():
    results = [{
        "relative": "paths/gtb-blue.ahk",
        "logs": ["stub builtin nm_Walk() - not implemented (logged)"],
    }]
    report = census.aggregate_runtime(results, {"NM_WALK"})
    assert report["unknown_load_bearing"] == []
    assert report["hits"][0]["verdict"] == "cross-file"


def test_aggregate_keeps_real_unknowns():
    results = [{
        "relative": "submacros/Heartbeat.ahk",
        "logs": ["stub builtin IniRead() - not implemented (logged)"],
    }]
    report = census.aggregate_runtime(results, {"nm_Walk"})
    assert [h["name"] for h in report["unknown_load_bearing"]] == ["IniRead"]


def test_assign_targets_are_grouped_by_container():
    assert census.group_hit_name(
        "assign-target", "'bitmaps[\"day\"][\"ant\"]'") == "bitmaps[...]"
    assert census.group_hit_name(
        "assign-target", "'settings[\"x\"]'") == "settings[...]"
    assert census.group_hit_name(
        "assign-target", "'(bitmaps := Map()).CaseSense'") == "(bitmaps"
    assert census.group_hit_name(
        "assign-target", "'Inner\"Y\", N := \"X\"1'") == "Inner"
    assert census.group_hit_name("for", "for-in") == "for-in"


def test_worker_deadline_returns_partial_inventory(tmp_path):
    script = tmp_path / "spin.ahk"
    script.write_text(
        "#Requires AutoHotkey v2.0\n"
        "Loop 100000000\n"
        "{\n"
        "    x := A_Index\n"
        "}\n",
        encoding="utf-8",
    )
    started = time.monotonic()
    result = census.runtime_worker(str(script), max_loop=10, deadline=0.25)
    elapsed = time.monotonic() - started
    assert result["deadline_hit"] is True
    assert elapsed < 2.0
