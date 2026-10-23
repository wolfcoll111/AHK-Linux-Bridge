"""Tests for the AHK ``#Include`` preprocessor (v0.5)."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from ahk_bridge import parser as P
from ahk_bridge.includes import IncludeError, IncludeLoader, expand_includes, load_script

CORPUS = Path(os.path.expanduser("~/Games/NatroMacro/src"))


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_nested_include_is_relative_to_includer(tmp_path):
    write(tmp_path / "main.ahk", '#Include "sub\\a.ahk"\ny := 2\n')
    write(tmp_path / "sub" / "a.ahk", '#Include "b.ahk"\nx := 1\n')
    write(tmp_path / "sub" / "b.ahk", "deep := 3\n")
    ex = expand_includes(str(tmp_path / "main.ahk"))
    assert "deep := 3" in ex.lines
    assert "x := 1" in ex.lines
    assert ex.lines[-1] == "y := 2"
    assert ex.lines[-2] == "x := 1"
    assert [Path(f).name for f in ex.files] == ["main.ahk", "a.ahk", "b.ahk"]
    # Every spliced line maps back to the file it came from.
    assert ex.source_of(ex.lines.index("deep := 3"))[0].endswith("b.ahk")
    assert ex.source_of(ex.lines.index("deep := 3"))[1] == 1


def test_directory_include_changes_base_for_current_file_only(tmp_path):
    write(tmp_path / "main.ahk",
          '#Include "%A_ScriptDir%\\lib"\n'
          '#Include "one.ahk"\n'
          '#Include "nested\\two.ahk"\n')
    write(tmp_path / "lib" / "one.ahk", "one := 1\n")
    write(tmp_path / "lib" / "nested" / "two.ahk", "two := 2\n")
    ex = expand_includes(str(tmp_path / "main.ahk"))
    assert "one := 1" in ex.lines
    assert "two := 2" in ex.lines
    dirs = [r for r in ex.records if r.status == "directory"]
    assert len(dirs) == 1


def test_nested_include_uses_its_own_directory_not_parent_base(tmp_path):
    write(tmp_path / "main.ahk", '#Include "lib"\n#Include "outer.ahk"\n')
    write(tmp_path / "lib" / "outer.ahk", '#Include "inner.ahk"\nouter := 1\n')
    write(tmp_path / "lib" / "inner.ahk", "inner := 1\n")
    ex = expand_includes(str(tmp_path / "main.ahk"))
    assert "inner := 1" in ex.lines
    assert "outer := 1" in ex.lines


def test_include_once_vs_include_again(tmp_path):
    write(tmp_path / "main.ahk",
          '#Include "a.ahk"\n#Include "a.ahk"\n#IncludeAgain "a.ahk"\n')
    write(tmp_path / "a.ahk", "marker += 1\n")
    ex = expand_includes(str(tmp_path / "main.ahk"))
    assert ex.lines.count("marker += 1") == 2
    statuses = [r.status for r in ex.records]
    assert statuses == ["ok", "once", "ok"]
    assert [r.directive for r in ex.records] == ["Include", "Include", "IncludeAgain"]


def test_include_inside_function_with_indentation(tmp_path):
    write(tmp_path / "main.ahk",
          "outer() {\n"
          "\tif true {\n"
          "\t\t#Include \"helper.ahk\"\n"
          "\t\treturn helper()\n"
          "\t}\n"
          "}\n")
    write(tmp_path / "helper.ahk", "helper() {\n\treturn 42\n}\n")
    sc, ex = load_script(str(tmp_path / "main.ahk"))
    # Nested function definitions are hoisted, matching AHK's load-time
    # exposure of functions included inside GUI handlers.
    assert "helper" in sc.functions
    assert "outer" in sc.functions
    assert all(type(x).__name__ != "Include" for x in sc.auto_section)


def test_missing_include_ignored_with_star_i(tmp_path):
    write(tmp_path / "main.ahk", '#Include *i "%A_ScriptDir%\\nope.ahk"\nx := 1\n')
    ex = expand_includes(str(tmp_path / "main.ahk"))
    assert ex.records[0].status == "ignored"
    assert ex.records[0].argument.startswith("*i")
    assert ex.warnings
    assert "x := 1" in ex.lines


def test_missing_include_is_a_clear_error(tmp_path):
    write(tmp_path / "main.ahk", '#Include "nope.ahk"\n')
    with pytest.raises(IncludeError) as err:
        expand_includes(str(tmp_path / "main.ahk"))
    assert "nope.ahk" in str(err.value)
    assert "main.ahk:1" in str(err.value)


def test_cycle_is_detected(tmp_path):
    write(tmp_path / "a.ahk", '#Include "b.ahk"\n')
    write(tmp_path / "b.ahk", '#Include "a.ahk"\n')
    with pytest.raises(IncludeError, match="cycle"):
        expand_includes(str(tmp_path / "a.ahk"))


def test_backslash_unquoted_and_case_insensitive(tmp_path):
    write(tmp_path / "Main.ahk", "#Include sub\\Hello.ahk\n")
    write(tmp_path / "SUB" / "hello.AHK", "x := 1\n")
    ex = expand_includes(str(tmp_path / "Main.ahk"))
    assert "x := 1" in ex.lines


def test_extension_is_appended(tmp_path):
    write(tmp_path / "main.ahk", "#Include helper\n")
    write(tmp_path / "helper.ahk", "x := 1\n")
    ex = expand_includes(str(tmp_path / "main.ahk"))
    assert "x := 1" in ex.lines


def test_standard_library_include(tmp_path):
    write(tmp_path / "main.ahk", "#Include <Util>\n")
    write(tmp_path / "Lib" / "Util.ahk", "util() {\n\treturn 1\n}\n")
    sc, ex = load_script(str(tmp_path / "main.ahk"))
    assert "util" in sc.functions
    assert ex.records[0].status == "library"


def test_include_inside_continuation_string_is_left_verbatim(tmp_path):
    write(tmp_path / "main.ahk",
          'script := "\n'
          "(\n"
          "#Include \"not_real.ahk\"\n"
          ')"\n')
    ex = expand_includes(str(tmp_path / "main.ahk"))
    assert ex.records == []
    assert "#Include" in ex.text
    # The parser must still see one generated script, not an include.
    sc = ex.parse()
    assert not any(type(x).__name__ == "Include" for x in sc.auto_section)


def test_bitmap_assignment_survives_expansion(tmp_path):
    write(tmp_path / "main.ahk", '#Include "bitmap.ahk"\n')
    write(tmp_path / "bitmap.ahk",
          'bitmaps["jelly"] := Gdip_BitmapFromBase64("AAAA")\n')
    sc, ex = load_script(str(tmp_path / "main.ahk"))
    assert 'bitmaps["jelly"] := Gdip_BitmapFromBase64("AAAA")' in ex.lines
    assert not any(type(x).__name__ == "Include" for x in sc.auto_section)


def test_parse_logical_lines_tags_sources(tmp_path):
    write(tmp_path / "main.ahk", "x := 1\n#Include \"a.ahk\"\n")
    write(tmp_path / "a.ahk", "y := 2\n")
    ex = expand_includes(str(tmp_path / "main.ahk"))
    sc = ex.parse()
    sources = [getattr(n, "_source", None) for n in sc.auto_section]
    assert sources[0][1] == 1
    assert sources[1][0].endswith("a.ahk")


@pytest.mark.skipif(not (CORPUS / "submacros/natro_macro.ahk").exists(),
                    reason="Natro corpus not installed")
def test_natro_main_include_tree_expands():
    start = time.monotonic()
    ex = expand_includes(str(CORPUS / "submacros/natro_macro.ahk"))
    elapsed = time.monotonic() - start
    sc = ex.parse()
    assert "Gdip_Startup" in sc.functions
    assert "Gdip_ImageSearch" in sc.functions
    assert "nm_OpenMenu" in sc.functions
    assert "HashFile" in sc.functions or "HashFile" in ex.text
    assert 'bitmaps[' in ex.text
    assert not any(type(x).__name__ == "Include" for x in sc.auto_section)
    assert not any(type(x).__name__ == "Include"
                   for fn in sc.functions.values() for x in fn.body)
    # The top-level `return` at natro_macro.ahk:3573 ends auto-execute.
    # No function body or main-loop line after it may leak into auto.
    main_auto = [
        getattr(node, "_source", (None, 0))[1]
        for node in sc.auto_section
        if (getattr(node, "_source", (None, ""))[0] or "").endswith(
            "natro_macro.ahk")]
    assert main_auto
    assert max(main_auto) <= 3573
    assert not (set(main_auto) & {6615, 6901, 11032, 13723, 14228})
    assert "nm_Start" in sc.functions
    assert len(ex.files) >= 30
    # The corpus loader is part of the CLI startup path; keep it bounded.
    assert elapsed < 10.0
