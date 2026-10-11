"""Ingest a GCCP ``sir-configuration`` release package.

Accepts either the distributed ``.zip`` or an already-extracted directory. The
package is the source of truth, so ingestion is idempotent per version: loading
the same version twice replaces its rows rather than duplicating them.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session

from tools.core.models import (
    ConfigPackage, CtryProcMapping, ReleaseNoteEntry, SirAttribute, SirDef, SirgDef,
)

_VERSION_RE = re.compile(r"sir-configuration-v?\.?([0-9][^/\\]*?)(?:\s*\(\d+\))?(?:\.zip)?$", re.IGNORECASE)


@dataclass
class PackageIngestResult:
    version: str
    source_name: str
    sirg: int = 0
    sir: int = 0
    attributes: int = 0
    mappings: int = 0
    release_entries: int = 0
    unparseable: list[str] = field(default_factory=list)
    #: Rows the CSV carried that are not data -- working notes typed into the file.
    malformed_mappings: list[str] = field(default_factory=list)


class _Source:
    """Uniform reader over a zip or a directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._zip: Optional[zipfile.ZipFile] = None
        self._root = ""
        if path.is_file() and path.suffix.lower() == ".zip":
            self._zip = zipfile.ZipFile(path)
            tops = {n.split("/")[0] for n in self._zip.namelist() if n.strip()}
            # Packages ship wrapped in a single versioned directory.
            if len(tops) == 1:
                self._root = f"{tops.pop()}/"
        elif not path.is_dir():
            raise FileNotFoundError(f"not a package zip or directory: {path}")

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def read_text(self, rel: str) -> Optional[str]:
        if self._zip is not None:
            try:
                return self._zip.read(self._root + rel).decode("utf-8-sig")
            except KeyError:
                return None
        target = self.path / rel
        return target.read_text(encoding="utf-8-sig") if target.exists() else None

    def iter_json(self, folder: str) -> Iterator[tuple[str, str]]:
        """Yield ``(stem, text)`` for every ``*.json`` under *folder*."""
        if self._zip is not None:
            prefix = f"{self._root}{folder}/"
            for name in self._zip.namelist():
                if name.startswith(prefix) and name.lower().endswith(".json"):
                    stem = Path(name).stem
                    yield stem, self._zip.read(name).decode("utf-8-sig")
            return
        directory = self.path / folder
        if not directory.is_dir():
            return
        for file in sorted(directory.glob("*.json")):
            yield file.stem, file.read_text(encoding="utf-8-sig")


def detect_version(path: Path) -> str:
    """Pull the version out of the package filename or directory name."""
    name = path.name
    match = _VERSION_RE.search(name)
    if match:
        return match.group(1).strip()
    return name


def _rows(text: Optional[str]) -> list[dict[str, str]]:
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, str]] = []
    for row in reader:
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if any(clean.values()):
            out.append(clean)
    return out


def _flatten_entities(
    entities: Any, path: str = "", out: Optional[list[dict[str, Any]]] = None
) -> list[dict[str, Any]]:
    """Walk ``Ent[]`` recursively, collecting every attribute with its path.

    Nesting reaches seven levels in the shipped package, so a single-level walk
    silently misses most attributes.
    """
    if out is None:
        out = []
    for ent in entities or []:
        if not isinstance(ent, dict):
            continue
        here = f"{path}/{ent.get('Nm') or ent.get('Id') or '?'}"
        for att in ent.get("Att") or []:
            if not isinstance(att, dict) or not att.get("Id"):
                continue
            out.append({
                "id": att["Id"],
                "ent_path": here,
                "nm": att.get("Nm"),
                "att_ty": att.get("AttTy"),
                "is_mandatory": bool(att.get("isMan")),
                "msg_positions": att.get("AttMsgPos") or [],
            })
        _flatten_entities(ent.get("Ent"), here, out)
    return out


def _unwrap(doc: Any) -> Optional[dict[str, Any]]:
    """Definitions ship as a single-element list wrapping ``ShpInfReqDef``."""
    if isinstance(doc, list):
        doc = doc[0] if doc else None
    if not isinstance(doc, dict):
        return None
    node = doc.get("ShpInfReqDef", doc)
    return node if isinstance(node, dict) else None


def parse_release_notes(text: Optional[str]) -> list[tuple[str, str, str]]:
    """Extract ``(ctry, sirg_cd, sir_id)`` triples claimed by the release notes."""
    out: list[tuple[str, str, str]] = []
    if not text:
        return out
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and len(parts[0]) == 2 and parts[0].isalpha() and parts[2].lower().endswith(".json"):
            out.append((parts[0].upper(), parts[1].upper(), parts[2][:-5]))
    return out


def ingest_package(session: Session, path: str | Path, version: Optional[str] = None) -> PackageIngestResult:
    """Load a package into the catalog tables, replacing that version in place."""
    path = Path(path)
    version = version or detect_version(path)
    src = _Source(path)
    result = PackageIngestResult(version=version, source_name=path.name)

    try:
        # Replace this version wholesale -- ingestion must be re-runnable. Other
        # versions are untouched, so two packages can be held and compared.
        for model in (SirgDef, SirDef, SirAttribute, CtryProcMapping, ReleaseNoteEntry):
            session.execute(delete(model).where(model.package_version == version))
        session.flush()

        for row in _rows(src.read_text("ShpInfReqGrpDef.csv")):
            sirg_id = row.get("ShpInfReqGrpDef.Id")
            if not sirg_id:
                continue
            session.add(SirgDef(
                id=sirg_id,
                cd=row.get("ShpInfReqGrpDef.Cd", ""),
                nm=row.get("ShpInfReqGrpDef.Nm", ""),
                dsc=row.get("ShpInfReqGrpDef.Dsc") or None,
                package_version=version,
            ))
            result.sirg += 1

        seen_map: set[tuple[str, str, str, str]] = set()
        for row in _rows(src.read_text("ShpInfReqDefInShpInfReqGrpDefOfCtryProc.csv")):
            key = (
                row.get("CtryProc.DhlCtryCd", ""),
                row.get("CtryProc.ProcLvlCd", ""),
                row.get("ShpInfReqGrpDef.Id", ""),
                row.get("ShpInfReqDef.Id", ""),
            )
            if not key[0] or not key[3]:
                # The shipped CSV contains a hand-typed working note in place of a
                # row. Record it rather than dropping it silently.
                note = row.get("ShpInfReqGrpDef.Id") or "(blank row)"
                result.malformed_mappings.append(note)
                continue
            if key in seen_map:
                continue
            seen_map.add(key)
            session.add(CtryProcMapping(
                ctry_cd=key[0], proc_lvl_cd=key[1], sirg_id=key[2], sir_id=key[3],
                package_version=version,
            ))
            result.mappings += 1

        for stem, text in src.iter_json("sir definitions"):
            try:
                node = _unwrap(json.loads(text))
            except (json.JSONDecodeError, IndexError):
                result.unparseable.append(stem)
                continue
            if node is None:
                result.unparseable.append(stem)
                continue
            ui = node.get("UICmpt") or {}
            session.add(SirDef(
                id=node.get("Id") or stem,
                nm=node.get("Nm") or "",
                dsc=node.get("Dsc"),
                cmpt_nm=ui.get("CmptNm"),
                cmpt_ty=ui.get("CmptTy"),
                ctry_cd=(node.get("LedOwnOrgn") or {}).get("CtryCd"),
                derived_from_id=(node.get("DrvdFromShpInfReqDef") or {}).get("Id"),
                sensitivity=node.get("PrsnDatSenstyClssLvl"),
                apply_all=bool(node.get("ApplyAllInd")),
                package_version=version,
            ))
            result.sir += 1
            for att in _flatten_entities(node.get("Ent")):
                session.add(SirAttribute(
                    att_id=att["id"],
                    sir_id=node.get("Id") or stem,
                    package_version=version,
                    ent_path=att["ent_path"],
                    nm=att["nm"],
                    att_ty=att["att_ty"],
                    is_mandatory=att["is_mandatory"],
                    msg_positions=att["msg_positions"],
                ))
                result.attributes += 1

        notes_text = src.read_text("Release-Notes.md")
        for ctry, sirg_cd, sir_id in parse_release_notes(notes_text):
            session.add(ReleaseNoteEntry(
                ctry_cd=ctry, sirg_cd=sirg_cd, sir_id=sir_id, package_version=version,
            ))
            result.release_entries += 1

        session.merge(ConfigPackage(
            version=version,
            source_name=path.name,
            sirg_count=result.sirg,
            sir_count=result.sir,
            mapping_count=result.mappings,
            release_notes=notes_text,
        ))
        session.flush()
    finally:
        src.close()

    return result
