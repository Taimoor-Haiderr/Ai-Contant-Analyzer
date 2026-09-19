"""
Command-line test interface (Phase 1 only).

This menu exists so the engine can be exercised before any frontend is built.
It contains no business logic: every option calls a function in `api.py`, which
is exactly what the Phase 2 web layer will do.

Run:  python app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import api
from config import INPUT_DIR, OUTPUT_DIR, ensure_directories, get_settings

MENU = """
============================================================
  AI CONTENT ANALYZER & NATURAL REWRITER  -  Phase 1 CLI
============================================================
   1. Analyze text            7. Analyze CSV
   2. Rewrite text            8. Rewrite CSV
   3. Analyze PDF             9. Analyze XLSX
   4. Rewrite PDF            10. Rewrite XLSX
   5. Analyze DOCX           11. Generate report from last result
   6. Rewrite DOCX           12. Exit
  ---------------------------------------------------------
   c. Show configuration      s. Create sample test files
============================================================
"""

_last_result: dict | None = None


# ---------------------------------------------------------------------------
# Small console helpers
# ---------------------------------------------------------------------------
def header(title: str) -> None:
    print("\n" + "-" * 60)
    print(title)
    print("-" * 60)


def ask_path(kind: str) -> str | None:
    print(f"\nEnter the path to your {kind} file.")
    print(f"(Tip: put files in '{INPUT_DIR}' and just type the file name.)")
    raw = input("Path: ").strip().strip('"').strip("'")
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.exists():
        alternative = INPUT_DIR / raw
        if alternative.exists():
            return str(alternative)
    return str(candidate)


def ask_multiline() -> str:
    print("\nPaste or type your text. Finish with a line containing only 'END'.")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().upper() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def show_error(result: dict) -> None:
    error = result.get("error", {})
    print("\n[FAILED] " + str(error.get("message", "Unknown error")))
    if error.get("detail"):
        print("         " + str(error["detail"]))
    if error.get("code") == "missing_api_key":
        print("         Set TEST_MODE=true in .env to run without a model.")


def show_analysis(result: dict) -> None:
    analysis = result.get("analysis") or {}
    statistics = analysis.get("statistics", {})
    header("ANALYSIS")
    print(f"Source           : {result.get('source')}")
    print(f"Mode             : {analysis.get('mode')} ({analysis.get('model')})")
    print(f"Indication level : {analysis.get('ai_likelihood')}")
    print(f"Confidence       : {analysis.get('confidence')}")
    print(f"Readability      : {analysis.get('readability')}")
    print(f"Words / sentences: {statistics.get('word_count')} / "
          f"{statistics.get('sentence_count')}")
    print(f"Chunks analysed  : {analysis.get('chunks_processed')}/"
          f"{analysis.get('chunks_total')}")
    print("\nAssessment:")
    print("  " + (analysis.get("overall_assessment") or "")[:600])

    indicators = analysis.get("indicators") or []
    if indicators:
        print(f"\nIndicators ({len(indicators)}):")
        for indicator in indicators[:8]:
            print(f"  [{indicator['severity']}] {indicator['type']}")
            print(f"      {indicator['explanation'][:160]}")

    flagged = analysis.get("flagged_passages") or []
    if flagged:
        print(f"\nFlagged passages ({len(flagged)}), showing up to 3:")
        for passage in flagged[:3]:
            print(f"  - ({passage['strength']}) {passage['original'][:120]}")
            print(f"    reason: {passage['reason'][:140]}")

    for warning in (result.get("extraction", {}).get("warnings") or []):
        print(f"\n[warning] {warning}")


def show_rewrite(result: dict) -> None:
    changes = result.get("changes") or {}
    summary = changes.get("summary", {})
    header("REWRITE")
    print(f"Source            : {result.get('source')}")
    print(f"Total changes     : {summary.get('total_changes')} "
          f"(major {summary.get('major_changes')}, minor {summary.get('minor_changes')})")
    print(f"Words before/after: {summary.get('original_word_count')} -> "
          f"{summary.get('rewritten_word_count')}")
    print(f"Meaning           : {summary.get('meaning_preservation_status')}")
    print(f"Facts             : {summary.get('facts_preserved_status')}")

    by_type = summary.get("changes_by_type") or {}
    if by_type:
        print("\nChanges by type:")
        for change_type, count in by_type.items():
            print(f"  - {change_type}: {count}")

    for example in (changes.get("examples") or [])[:3]:
        print(f"\n  [{example['change_type']}]")
        print(f"  BEFORE: {example['original'][:160]}")
        print(f"  AFTER : {example['rewritten'][:160]}")

    rewritten = (result.get("rewrite") or {}).get("rewritten")
    if rewritten:
        print("\nRewritten preview:")
        print("  " + rewritten[:500].replace("\n", "\n  "))

    if result.get("output_file"):
        print(f"\nNew file written : {result['output_file']}")
        print("Original file    : unchanged")


def finish(result: dict, export: bool = True) -> None:
    """Show a result and offer to export it."""
    global _last_result
    if not result.get("ok"):
        show_error(result)
        return
    _last_result = result

    if result.get("analysis"):
        show_analysis(result)
    if result.get("changes"):
        show_rewrite(result)

    if export and input("\nExport report and outputs? [Y/n]: ").strip().lower() != "n":
        exported = api.export_result(result)
        if exported.get("ok"):
            print("\nFiles written:")
            for key, path in exported["files"].items():
                print(f"  {key:22s} {path}")
        else:
            show_error(exported)


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------
def action_analyze_text() -> None:
    text = ask_multiline()
    if not text.strip():
        print("No text entered.")
        return
    finish(api.analyze_text(text))


def action_rewrite_text() -> None:
    text = ask_multiline()
    if not text.strip():
        print("No text entered.")
        return
    finish(api.rewrite_text(text))


def action_file(kind: str, function, rewriting: bool) -> None:
    path = ask_path(kind)
    if not path:
        print("No path entered.")
        return
    print("\nWorking... (large files are chunked automatically)")
    finish(function(path))


def action_show_config() -> None:
    settings = get_settings()
    header("CONFIGURATION")
    for key, value in settings.describe().items():
        print(f"  {key:24s}: {value}")
    print(f"  {'input folder':24s}: {INPUT_DIR}")
    print(f"  {'output folder':24s}: {OUTPUT_DIR}")
    if settings.use_mock:
        print("\n  Running in OFFLINE TEST MODE - no model will be contacted.")
    elif not settings.has_api_key:
        print("\n  WARNING: MODEL_API_KEY is not set. Set it in .env, or set "
              "TEST_MODE=true.")


def action_samples() -> None:
    try:
        from make_samples import create_samples
    except ImportError:
        print("make_samples.py was not found next to app.py.")
        return
    created = create_samples()
    header("SAMPLE FILES CREATED")
    for path in created:
        print(f"  {path}")


def action_report() -> None:
    if not _last_result:
        print("\nRun an analysis or rewrite first.")
        return
    written = api.generate_report(_last_result, formats=("json", "txt", "html", "pdf"))
    if written.get("ok"):
        header("REPORT FILES")
        for key, path in written["files"].items():
            print(f"  {key:12s} {path}")
    else:
        show_error(written)


ACTIONS = {
    "1": ("Analyze text", action_analyze_text),
    "2": ("Rewrite text", action_rewrite_text),
    "3": ("Analyze PDF", lambda: action_file("PDF", api.analyze_pdf, False)),
    "4": ("Rewrite PDF", lambda: action_file("PDF", api.rewrite_pdf, True)),
    "5": ("Analyze DOCX", lambda: action_file("DOCX", api.analyze_docx, False)),
    "6": ("Rewrite DOCX", lambda: action_file("DOCX", api.rewrite_docx, True)),
    "7": ("Analyze CSV", lambda: action_file("CSV", api.analyze_csv, False)),
    "8": ("Rewrite CSV", lambda: action_file("CSV", api.rewrite_csv, True)),
    "9": ("Analyze XLSX", lambda: action_file("XLSX", api.analyze_xlsx, False)),
    "10": ("Rewrite XLSX", lambda: action_file("XLSX", api.rewrite_xlsx, True)),
    "11": ("Generate report", action_report),
    "c": ("Configuration", action_show_config),
    "s": ("Create samples", action_samples),
}


def main() -> int:
    ensure_directories()
    settings = get_settings()
    print(MENU)
    if settings.use_mock:
        print("Running in OFFLINE TEST MODE (TEST_MODE=true): local heuristics only.\n")
    elif not settings.has_api_key:
        print("No MODEL_API_KEY found. Add one to .env, or set TEST_MODE=true to "
              "test the pipeline offline.\n")

    while True:
        try:
            choice = input("Select an option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if choice in {"12", "q", "exit", "quit"}:
            print("Bye.")
            return 0
        if choice in {"m", "menu", "?"}:
            print(MENU)
            continue

        action = ACTIONS.get(choice)
        if not action:
            print("Unknown option. Type 'm' for the menu or '12' to exit.")
            continue

        try:
            action[1]()
        except KeyboardInterrupt:
            print("\nCancelled.")
        except Exception as exc:  # the CLI must never crash on user input
            print(f"\n[unexpected error] {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
