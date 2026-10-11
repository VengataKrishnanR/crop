"""Command line entry points.

``ccre bootstrap`` is the fastest way to see the platform do real work: it
ingests both artifacts from ``../Reference/`` and prints the validation report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from tools.core.config import SETTINGS
from tools.core.db import init_db, session_scope
from tools.validation import available_checks, load_snapshot, run_checks, validate_rule_set

_SEV_MARK = {"blocker": "BLOCK", "caution": "CHECK", "info": " info"}


def _find_reference(pattern: str) -> Optional[Path]:
    matches = sorted(SETTINGS.reference_dir.glob(pattern))
    return matches[0] if matches else None


def _print_report(report) -> None:  # noqa: ANN001 -- local formatting helper
    print(f"\n  checks run     : {len(report.checks_run)}")
    print(f"  blocking       : {len(report.blockers)}")
    print(f"  to confirm     : {len(report.cautions)}")
    print(f"  informational  : {len(report.infos)}")
    print(f"  gate           : {'OPEN' if report.is_clean else 'LOCKED'}\n")
    for finding in report.sorted():
        print(f"  [{_SEV_MARK[finding.severity]}] {finding.code:16} {finding.where}")
        print(f"           {finding.message}")
        if finding.evidence:
            print(f"           evidence: {finding.evidence}")
        print()


def cmd_initdb(args: argparse.Namespace) -> int:
    init_db()
    print(f"schema created in {SETTINGS.database_url}")
    return 0


def cmd_ingest_package(args: argparse.Namespace) -> int:
    from tools.ingestion import ingest_package

    path = Path(args.path) if args.path else _find_reference("sir-configuration*")
    if path is None:
        print("no package found; pass a path", file=sys.stderr)
        return 2
    init_db()
    with session_scope() as session:
        result = ingest_package(session, path, args.version)
    print(
        f"package {result.version}: {result.sirg} groups, {result.sir} definitions, "
        f"{result.attributes} attributes, {result.mappings} mappings, "
        f"{result.release_entries} release-note entries"
    )
    if result.unparseable:
        print(f"  unparseable definitions: {len(result.unparseable)}")
    return 0


def cmd_ingest_workbook(args: argparse.Namespace) -> int:
    from tools.ingestion import ingest_workbook

    path = Path(args.path) if args.path else _find_reference("M2c*.xlsx")
    if path is None:
        print("no workbook found; pass a path", file=sys.stderr)
        return 2
    init_db()
    with session_scope() as session:
        result = ingest_workbook(session, path, args.version, args.case_id)
    print(
        f"workbook {result.version}: {result.rules} rules, {result.bindings} bindings, "
        f"{result.mirror_sir} mirrored definitions, {result.mirror_sirg} mirrored mappings"
    )
    print(f"  rule set: {result.rule_set_id}")
    if result.unbound_rules:
        print(f"  rules with no binding: {len(result.unbound_rules)}")
    if result.orphan_bindings:
        print(f"  bindings with no rule : {len(result.orphan_bindings)}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    with session_scope() as session:
        report, run_id = validate_rule_set(
            session, args.rule_set_id, case_id=args.case_id, persist=not args.no_persist
        )
        if args.json:
            print(json.dumps(report.as_dict(), indent=2))
        else:
            _print_report(report)
            if run_id:
                print(f"  recorded as validation run {run_id}")
    return 0 if report.is_clean else 1


def cmd_checks(args: argparse.Namespace) -> int:
    for code, description in sorted(available_checks().items()):
        print(f"  {code:10} {description}")
    return 0


def cmd_expr(args: argparse.Namespace) -> int:
    from tools.core import grammar

    diagnostics = grammar.analyse(args.expression)
    try:
        print(f"  normalised : {grammar.normalise(args.expression)}")
    except grammar.ExpressionError as exc:
        print(f"  parse error: {exc.message}")
    for diag in diagnostics:
        print(f"  [{diag.severity:7}] {diag.code}: {diag.message}")
    if not diagnostics:
        print("  clean")
    return 0 if not any(d.severity == "error" for d in diagnostics) else 1


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Ingest both reference artifacts and validate what came out."""
    package = Path(args.package) if args.package else _find_reference("sir-configuration*")
    workbook = Path(args.workbook) if args.workbook else _find_reference("M2c*.xlsx")
    if package is None or workbook is None:
        print(
            f"need both artifacts; looked in {SETTINGS.reference_dir}\n"
            f"  package : {package or 'NOT FOUND'}\n  workbook: {workbook or 'NOT FOUND'}",
            file=sys.stderr,
        )
        return 2

    from tools.ingestion import ingest_package, ingest_workbook

    init_db()
    with session_scope() as session:
        pkg = ingest_package(session, package)
        print(
            f"package  {pkg.version}: {pkg.sirg} groups, {pkg.sir} definitions, "
            f"{pkg.mappings} mappings, {pkg.attributes} attributes"
        )
        wb = ingest_workbook(session, workbook)
        print(f"workbook {wb.version}: {wb.rules} rules, {wb.bindings} bindings")
        rule_set_id = wb.rule_set_id

    with session_scope() as session:
        report, _ = validate_rule_set(session, rule_set_id, persist=True)
        _print_report(report)

    print(f"  rule set id: {rule_set_id}")
    print("  next: ccre validate <rule_set_id>, or START.bat / uvicorn server.app:app --port 8000")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ccre", description="CCRE onboarding platform")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("initdb", help="create the schema").set_defaults(fn=cmd_initdb)
    sub.add_parser("checks", help="list the deterministic check register").set_defaults(fn=cmd_checks)

    p = sub.add_parser("ingest-package", help="ingest a sir-configuration package (zip or dir)")
    p.add_argument("path", nargs="?")
    p.add_argument("--version")
    p.set_defaults(fn=cmd_ingest_package)

    p = sub.add_parser("ingest-workbook", help="ingest an M2C workbook")
    p.add_argument("path", nargs="?")
    p.add_argument("--version")
    p.add_argument("--case-id")
    p.set_defaults(fn=cmd_ingest_workbook)

    p = sub.add_parser("validate", help="validate a rule set")
    p.add_argument("rule_set_id")
    p.add_argument("--case-id")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-persist", action="store_true")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("expr", help="parse and check one condition expression")
    p.add_argument("expression")
    p.set_defaults(fn=cmd_expr)

    p = sub.add_parser("bootstrap", help="ingest both reference artifacts and validate")
    p.add_argument("--package")
    p.add_argument("--workbook")
    p.set_defaults(fn=cmd_bootstrap)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    # Findings carry middots and arrows; the Windows console defaults to cp1252.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
