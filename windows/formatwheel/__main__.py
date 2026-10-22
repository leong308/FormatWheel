"""Windows tray entry point and the upstream-compatible diagnostic CLI."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import os
import sys


def main(argv=None):
    # Frozen Windows console apps otherwise inherit legacy encodings when redirected.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="FormatWheel for Windows — local file conversion wheel")
    parser.add_argument("files", nargs="*", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ids", action="store_true", help="List the same 73 action IDs as macOS")
    mode.add_argument("--list", nargs="*", type=Path, metavar="FILE")
    mode.add_argument("--run", nargs="+", metavar="ACTION_OR_FILE")
    mode.add_argument("--scan", nargs="+", type=Path, metavar="FILE")
    mode.add_argument("--doctor", action="store_true", help="Report conversion backend readiness")
    mode.add_argument("--snapshot", type=Path, metavar="PNG")
    mode.add_argument("--weapons", type=Path, metavar="PNG")
    mode.add_argument("--glyphs", type=Path, metavar="PNG")
    mode.add_argument("--sounds", type=Path, metavar="FOLDER")
    mode.add_argument("--preview", action="store_true")
    parser.add_argument("--files", dest="snapshot_files", nargs="*", type=Path)
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--hover", type=int)
    parser.add_argument("--crew", choices=("online", "michael", "franklin", "trevor"))
    parser.add_argument("--size", choices=("small", "medium", "large"))
    parser.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FormatWheel"
    log_dir.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(handlers=[RotatingFileHandler(log_dir / "FormatWheel.log", maxBytes=512000, backupCount=1, encoding="utf-8")], level=logging.INFO, format="%(asctime)s %(message)s")
    from .catalog import all_ids, context
    from .engine import Engine, scan_privacy, action_availability
    if args.ids:
        print("\n".join(all_ids()))
        return 0
    if args.doctor:
        report = {}
        for action in all_ids():
            # Dependency readiness is independent of file-count requirements.
            samples = [Path("one.pdf"), Path("two.pdf")] if action == "pdf.merge" else [Path("sample.docx")] if action.startswith("doc.") else []
            enabled, note = action_availability(action, samples)
            report[action] = {"ready": enabled, "note": note}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if all(entry["ready"] for entry in report.values()) else 2
    if args.list is not None:
        selection = context(args.list)
        print(f"kind: {selection.kind}  headline: {selection.headline}  summary: {selection.summary}")
        for page in selection.pages:
            print(f"[{page.name}]")
            for index, option in enumerate(page.slots):
                print(f"  {index}: " + (f"{option.id}  {option.title}" + (f" (disabled: {option.note})" if not option.enabled else "") if option else "—"))
        return 0
    if args.scan:
        for path in args.scan:
            wanted = scan_privacy(path)
            print(f"{path.name}: {'★' * wanted.level}{'☆' * (5 - wanted.level)}  {' · '.join(wanted.reasons)}")
        return 0
    if args.run:
        action, *files = args.run
        try:
            result = Engine.run(action, [Path(p) for p in files])
            if result.clip is not None:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance() or QApplication([])
                app.clipboard().setText(result.clip)
                app.processEvents()
            print(f"OK {action}: {result.note}")
            for path in result.outputs:
                print(f"   -> {path}")
            if result.clip:
                print(result.clip)
            return 0
        except Exception as error:
            logging.exception("Conversion failed: %s", action)
            print(f"FAIL {action}: {error}", file=sys.stderr)
            return 1
    if sys.platform != "win32" and not args.snapshot:
        parser.error("The tray application requires Windows 10 or later.")
    if args.crew or args.size:
        from .settings import Settings
        settings = Settings()
        if args.crew:
            settings.set("crew", args.crew)
        if args.size:
            settings.set("size", args.size)
    if args.snapshot:
        from .ui import snapshot
        snapshot(args.snapshot, args.snapshot_files or args.files, page=args.page, hover=args.hover)
        return 0
    if args.weapons or args.glyphs:
        from .ui import export_contact_sheet
        export_contact_sheet(args.weapons or args.glyphs, weapons=bool(args.weapons))
        return 0
    if args.sounds:
        from .sound import Sounds
        from .settings import Settings
        Sounds(Settings()).export(args.sounds)
        return 0
    from .ui import run_gui
    return run_gui(args.files, preview=args.preview, background=args.background)


if __name__ == "__main__":
    raise SystemExit(main())
