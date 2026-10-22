"""Review a beta file (sir-configuration package) before it is used.

The review reads the zip in place — nothing is extracted or executed — and answers:

1. **Is the file safe and complete?**  zip paths, size, the three required parts.
2. **What version is it?**  from CHANGELOG (released heading), compared with the file name.
3. **Is it internally consistent?**  every mapping points at a known group and a shipped
   definition; definition ids match their file names; no typed notes in the CSV; the
   release notes are reflected in the mappings; what the changelog claims is true.
4. **How does it compare with the M2C workbook?**  the workbook's Technical SIRG tab is a
   copy of a package mapping: same (country, group) → same definition? which countries /
   mappings exist only on one side?
5. **What changes against the active package?**  mappings and countries added / removed.

Severity: ``error`` blocks activation · ``warning`` needs a look · ``info`` worth knowing.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

GROUPS_CSV = "ShpInfReqGrpDef.csv"
MAPPING_CSV = "ShpInfReqDefInShpInfReqGrpDefOfCtryProc.csv"
DEFS_DIR = "sir definitions/"
MAX_UNCOMPRESSED = 600 * 1024 * 1024
DSC_PLACEHOLDER = "to be added in future release"
_CHANGELOG_RELEASE = re.compile(r"^##\s*\[v?\.?([0-9][^\]]*)\]\s*-\s*(\d{4}-\d{2}-\d{2})", re.M)
_FILENAME_VERSION = re.compile(r"sir-configuration-v?\.?([0-9][^/\\]*?)(?:\s*\(\d+\))?(?:\.zip)?$", re.I)


def _finding(out: list, code: str, severity: str, message: str, details: Optional[list] = None) -> None:
    out.append({"code": code, "severity": severity, "message": message, "details": (details or [])[:50],
                "count": len(details or [])})


class _Zip:
    def __init__(self, path: Path):
        self.z = zipfile.ZipFile(path)
        names = [n for n in self.z.namelist() if n.strip()]
        tops = {n.split("/")[0] for n in names}
        self.root = (tops.pop() + "/") if len(tops) == 1 and any("/" in n for n in names) else ""
        self.names = names

    def rel(self, name: str) -> str:
        return name[len(self.root):] if name.startswith(self.root) else name

    def text(self, rel: str) -> Optional[str]:
        try:
            return self.z.read(self.root + rel).decode("utf-8-sig")
        except KeyError:
            return None

    def defs(self):
        for n in self.names:
            r = self.rel(n)
            if r.startswith(DEFS_DIR) and r.lower().endswith(".json"):
                yield r[len(DEFS_DIR):-5], n


def review_package(path: str | Path, workbook_mirror: Optional[dict] = None,
                   active: Optional[dict] = None) -> dict[str, Any]:
    """Review a package zip.

    ``workbook_mirror``: {"version": str, "rows": [(ctry, sirg_cd, sir_id, cmpt_nm), ...]} from the
    M2C Technical SIRG tab. ``active``: {"version": str, "mappings": {(ctry, sirg_cd, sir_id), ...}}.
    """
    path = Path(path)
    findings: list[dict[str, Any]] = []
    try:
        zf = _Zip(path)
    except zipfile.BadZipFile:
        _finding(findings, "NOT_A_ZIP", "error", "The file is not a zip archive.")
        return {"ok": False, "findings": findings, "summary": {}}

    # 1. safety and structure
    unsafe = [n for n in zf.names if n.startswith(("/", "\\")) or ".." in n.replace("\\", "/").split("/")]
    if unsafe:
        _finding(findings, "ZIP_UNSAFE_PATHS", "error", "Entries with absolute or '..' paths.", unsafe)
    total = sum(i.file_size for i in zf.z.infolist())
    if total > MAX_UNCOMPRESSED:
        _finding(findings, "ZIP_TOO_LARGE", "error", f"Uncompressed size {total // 2**20} MB exceeds the limit.")
    groups_txt, map_txt = zf.text(GROUPS_CSV), zf.text(MAPPING_CSV)
    defs = list(zf.defs())
    for part, present in ((GROUPS_CSV, groups_txt is not None), (MAPPING_CSV, map_txt is not None),
                          (DEFS_DIR, bool(defs))):
        if not present:
            _finding(findings, "MISSING_PART", "error", f"The package has no {part}.")
    if groups_txt is None or map_txt is None or not defs:
        return {"ok": False, "findings": findings, "summary": {"root": zf.root}}

    # 2. version
    changelog = zf.text("CHANGELOG.md") or ""
    rel = _CHANGELOG_RELEASE.search(changelog)
    declared, release_date = (rel.group(1).strip(), rel.group(2)) if rel else (None, None)
    fm = _FILENAME_VERSION.search(path.name) or _FILENAME_VERSION.search(zf.root.rstrip("/"))
    from_name = fm.group(1).strip() if fm else None
    if declared and from_name and declared != from_name:
        _finding(findings, "VERSION_MISMATCH", "warning",
                 f"The changelog's latest release is {declared}, the file name says {from_name}.")
    unreleased = changelog.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0] if "## [Unreleased]" in changelog else ""
    pending = [l.strip("- ").strip() for l in unreleased.splitlines() if l.strip().startswith("-")]

    # 3. consistency
    groups = list(csv.DictReader(io.StringIO(groups_txt)))
    gid = {(g.get("ShpInfReqGrpDef.Id") or "").strip(): g for g in groups if (g.get("ShpInfReqGrpDef.Id") or "").strip()}
    gcd = {g.get("ShpInfReqGrpDef.Cd", "").strip(): i for i, g in gid.items()}
    dup_codes = [c for c, n in Counter(g.get("ShpInfReqGrpDef.Cd", "").strip() for g in groups).items() if n > 1]
    if dup_codes:
        _finding(findings, "GROUP_CODE_DUPLICATE", "error", "Requirement group codes used twice.", dup_codes)
    placeholders = [g.get("ShpInfReqGrpDef.Cd") for g in groups
                    if (g.get("ShpInfReqGrpDef.Dsc") or "").strip().lower() == DSC_PLACEHOLDER]
    if placeholders:
        _finding(findings, "GROUP_DESCRIPTION_PLACEHOLDER", "info",
                 f"{len(placeholders)} of {len(groups)} group descriptions are '{DSC_PLACEHOLDER}'.", placeholders)
    if rel and placeholders and "Dsc" in changelog.split(rel.group(0), 1)[1].split("\n## [", 1)[0]:
        _finding(findings, "CHANGELOG_CLAIM_NOT_MET", "warning",
                 f"The changelog for {declared} says group descriptions were updated, but "
                 f"{len(placeholders)} still hold the placeholder.", [f"changelog {declared} ({release_date})"])

    lines = map_txt.splitlines()
    header = next(csv.reader([lines[0]])) if lines else []
    mappings, notes = [], []
    for i, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        parts = next(csv.reader([line]))
        if len(parts) >= 4 and re.fullmatch(r"[A-Z]{2}", parts[0].strip()):
            mappings.append({"line": i, **{h: (parts[k] if k < len(parts) else "") for k, h in enumerate(header)}})
        else:
            notes.append(f"line {i}: {line.strip()[:120]}")
    if notes:
        _finding(findings, "MAPPING_NOTE_ROW", "warning",
                 "Lines in the mapping CSV that are not data (typed notes) — they are skipped.", notes)
    C, P, G, S, F = ("CtryProc.DhlCtryCd", "CtryProc.ProcLvlCd", "ShpInfReqGrpDef.Id", "ShpInfReqDef.Id",
                     "ShpInfReqDef.FlNm")
    keys = Counter((m[C], m[P], m[G], m[S]) for m in mappings)
    dups = [f"{k[0]} {gid.get(k[2], {}).get('ShpInfReqGrpDef.Cd', k[2])} {k[3]}" for k, n in keys.items() if n > 1]
    if dups:
        _finding(findings, "MAPPING_DUPLICATE", "warning", "Mapping rows repeated.", dups)
    unknown_group = [f"line {m['line']}: {m[C]} {m[G]}" for m in mappings if m[G] not in gid]
    if unknown_group:
        _finding(findings, "MAPPING_GROUP_UNKNOWN", "error", "Mappings to a group that is not in the group list.",
                 unknown_group)

    def_ids, unreadable, id_mismatch, attributes = set(), [], [], 0
    def_meta: dict[str, dict] = {}
    for stem, name in defs:
        try:
            doc = json.loads(zf.z.read(name).decode("utf-8-sig"))
            node = doc[0] if isinstance(doc, list) else doc
            node = node.get("ShpInfReqDef", node) if isinstance(node, dict) else None
            node = node[0] if isinstance(node, list) else node
            if not isinstance(node, dict):
                raise ValueError("no ShpInfReqDef")
        except Exception as exc:                                   # noqa: BLE001
            unreadable.append(f"{stem}.json: {str(exc)[:80]}")
            continue
        if node.get("Id") != stem:
            id_mismatch.append(f"{stem}.json has Id {node.get('Id')}")
        def_ids.add(stem)

        def count(ents) -> int:
            n = 0
            for e in ents or []:
                if isinstance(e, dict):
                    n += len(e.get("Att") or []) + count(e.get("Ent"))
            return n
        n_att = count(node.get("Ent"))
        attributes += n_att
        def_meta[stem] = {"nm": node.get("Nm"), "cmpt_nm": (node.get("UICmpt") or {}).get("CmptNm"),
                          "ctry": (node.get("LedOwnOrgn") or {}).get("CtryCd"), "attributes": n_att}
    if unreadable:
        _finding(findings, "DEFINITION_UNREADABLE", "error", "Definition files that cannot be read.", unreadable)
    if id_mismatch:
        _finding(findings, "DEFINITION_ID_MISMATCH", "error", "Definition id differs from its file name.", id_mismatch)
    no_json = [f"line {m['line']}: {m[C]} {gid.get(m[G], {}).get('ShpInfReqGrpDef.Cd', '?')} → {m[S]}"
               for m in mappings if m[S] not in def_ids]
    if no_json:
        _finding(findings, "MAPPING_DEFINITION_MISSING", "error",
                 "Mappings to a definition whose file is not in the package.", no_json)
    bad_fn = [f"line {m['line']}: '{m.get(F, '')}'" for m in mappings
              if F in m and m.get(F, "") != f"{m[S]}.json"]
    if bad_fn:
        _finding(findings, "MAPPING_FILENAME", "warning",
                 "File name column differs from '<definition id>.json' (e.g. extra spaces).", bad_fn)
    mapped_defs = {m[S] for m in mappings}
    orphans = sorted(def_ids - mapped_defs)
    if orphans:
        _finding(findings, "DEFINITION_UNMAPPED", "info",
                 f"{len(orphans)} definition files are shipped but mapped to no country "
                 "(superseded versions? ask Support).", [f"{o} {def_meta.get(o, {}).get('cmpt_nm') or ''}" for o in orphans])
    procs = Counter(m[P] for m in mappings)
    if set(procs) != {"IMP_CLR"}:
        _finding(findings, "PROCESS_LEVELS", "info", f"Processing levels: {dict(procs)}.")

    notes_txt = zf.text("Release-Notes.md") or ""
    claimed = re.findall(r"^\s*([A-Z]{2})\s+([A-Z0-9]+)\s+([0-9a-f-]{36})\.json", notes_txt, re.M)
    rn_bad = [f"{c} {g} {s}" for c, g, s in claimed
              if s not in def_ids or not any(m[C] == c and m[S] == s for m in mappings)]
    if rn_bad:
        _finding(findings, "RELEASE_NOTE_NOT_REFLECTED", "warning",
                 "Release-note entries whose file is missing or not mapped for that country.", rn_bad)

    # 4. compared with the M2C workbook (Technical SIRG tab)
    pkg = {(m[C], gid.get(m[G], {}).get("ShpInfReqGrpDef.Cd", "?"), m[S]) for m in mappings}
    pkg_by_key = defaultdict(set)
    for c, g, s in pkg:
        pkg_by_key[(c, g)].add(s)
    workbook = None
    if workbook_mirror and workbook_mirror.get("rows"):
        wb = {(c, g, s) for c, g, s, _ in workbook_mirror["rows"]}
        wb_by_key = defaultdict(set)
        for c, g, s in wb:
            wb_by_key[(c, g)].add(s)
        differs = sorted(f"{c} {g}: workbook {', '.join(sorted(wb_by_key[(c, g)]))} · package "
                         f"{', '.join(sorted(pkg_by_key[(c, g)]))}"
                         for (c, g) in set(wb_by_key) & set(pkg_by_key) if wb_by_key[(c, g)] != pkg_by_key[(c, g)])
        wb_only_keys = sorted(set(wb_by_key) - set(pkg_by_key))
        pkg_only_keys = sorted(set(pkg_by_key) - set(wb_by_key))
        countries_wb_only = sorted({c for c, _ in wb_by_key} - {c for c, _ in pkg_by_key})
        workbook = {
            "workbook_version": workbook_mirror.get("version"),
            "same": sum(1 for k in set(wb_by_key) & set(pkg_by_key) if wb_by_key[k] == pkg_by_key[k]),
            "definition_differs": differs,
            "workbook_only": [f"{c} {g}" for c, g in wb_only_keys],
            "package_only": [f"{c} {g}" for c, g in pkg_only_keys],
            "countries_only_in_workbook": countries_wb_only,
            "countries_only_in_package": sorted({c for c, _ in pkg_by_key} - {c for c, _ in wb_by_key}),
        }
        if countries_wb_only:
            _finding(findings, "WORKBOOK_COUNTRIES_NOT_IN_PACKAGE", "warning",
                     f"The M2C workbook configures {len(countries_wb_only)} countr(ies) this package does not map "
                     "at all — their rules would have nothing to raise.", countries_wb_only)
        if differs:
            _finding(findings, "WORKBOOK_DEFINITION_DIFFERS", "warning",
                     "Same country and group, but the workbook and the package point at different definitions.",
                     differs)

    # 5. compared with the active package
    changes = None
    if active and active.get("mappings") is not None:
        a = set(active["mappings"])
        changes = {"active_version": active.get("version"),
                   "added": sorted(f"{c} {g} {s}" for c, g, s in pkg - a),
                   "removed": sorted(f"{c} {g} {s}" for c, g, s in a - pkg),
                   "countries_added": sorted({c for c, _, _ in pkg} - {c for c, _, _ in a}),
                   "countries_removed": sorted({c for c, _, _ in a} - {c for c, _, _ in pkg})}

    counts = Counter(f["severity"] for f in findings)
    return {
        "ok": counts.get("error", 0) == 0,
        "findings": findings,
        "counts": dict(counts),
        "summary": {
            "root": zf.root.rstrip("/"), "declared_version": declared, "release_date": release_date,
            "filename_version": from_name, "groups": len(groups), "mappings": len(mappings),
            "countries": len({m[C] for m in mappings}), "definitions": len(def_ids), "attributes": attributes,
            "processing_levels": dict(procs), "pending_in_changelog": pending,
            "release_note_entries": len(claimed),
        },
        "workbook": workbook,
        "changes_vs_active": changes,
    }
