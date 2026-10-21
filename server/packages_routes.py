"""Beta files (config packages): upload, review, activate — and the mapping explorer.

Admin:     upload a sir-configuration zip → it is stored by hash, reviewed, loaded into the
           catalog under its own version (never overwriting another file) → the admin
           activates it. Every check in the platform reads the ACTIVE package.
Internal:  the mapping explorer traces one requirement through both files:
           M2C rule → workbook Technical SIRG → package group → package mapping →
           definition → attributes (with message positions) ← SIR Reference bindings.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tools.core.config import REPO_ROOT
from tools.core.db import get_session
from tools.core.models import (
    AuditEvent, ConfigPackage, CtryProcMapping, PackageUpload, SirAttribute, SirDef, SirgDef,
)
from tools.core.packages import active_package_version, active_upload
from tools.package_review import review_package
from tools.reference import get_reference

from .auth import CurrentUser, require_admin, require_internal

router = APIRouter()
MAX_UPLOAD = 200 * 1024 * 1024


def _packages_dir() -> Path:
    d = Path(os.getenv("CCRE_DATA_DIR", str(REPO_ROOT / ".ccre_data"))) / "packages"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _workbook_mirror(session: Session) -> dict[str, Any]:
    reference = get_reference(session)
    version = reference.workbook_version()
    if not version:
        return {"version": None, "rows": []}
    rows = reference.mirror_sirg(version=version)
    return {"version": version, "rows": [(m.ctry_cd, m.sirg_cd, m.sir_id, m.cmpt_nm) for m in rows
                                         if m.ctry_cd and m.sirg_cd and m.sir_id]}


def _package_mappings(session: Session, version: Optional[str]) -> set[tuple[str, str, str]]:
    if not version:
        return set()
    codes = dict(session.execute(select(SirgDef.id, SirgDef.cd).where(SirgDef.package_version == version)).all())
    return {(c, codes.get(g, "?"), s) for c, g, s in session.execute(
        select(CtryProcMapping.ctry_cd, CtryProcMapping.sirg_id, CtryProcMapping.sir_id)
        .where(CtryProcMapping.package_version == version)).all()}


def _upload_out(u: PackageUpload, brief: bool = True) -> dict[str, Any]:
    r = u.review or {}
    out = {"id": u.id, "filename": u.filename, "sha256": u.sha256, "size": u.size, "version": u.version,
           "declared_version": u.declared_version, "release_date": u.release_date, "status": u.status,
           "uploaded_by": u.uploaded_by, "uploaded_at": u.uploaded_at.isoformat(),
           "decided_by": u.decided_by, "decided_at": u.decided_at.isoformat() if u.decided_at else None,
           "decision_note": u.decision_note, "ok": r.get("ok"), "counts": r.get("counts", {}),
           "summary": r.get("summary", {})}
    if not brief:
        out.update({"findings": r.get("findings", []), "workbook": r.get("workbook"),
                    "changes_vs_active": r.get("changes_vs_active")})
    return out


# --------------------------------------------------------------------------- #
# admin: beta files
# --------------------------------------------------------------------------- #

@router.get("/admin/packages", tags=["packages"])
def list_packages(user: CurrentUser = Depends(require_internal),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    ups = session.execute(select(PackageUpload).order_by(PackageUpload.uploaded_at.desc())).scalars()
    active = active_upload(session)
    return {"active_version": active_package_version(session),
            "active_upload_id": active.id if active else None,
            "legacy_active": active is None and active_package_version(session) is not None,
            "uploads": [_upload_out(u) for u in ups]}


@router.post("/admin/packages", tags=["packages"])
async def upload_package(file: UploadFile = File(...), user: CurrentUser = Depends(require_admin),
                         session: Session = Depends(get_session)) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "Upload the beta file as the .zip Support delivers (sir-configuration-v…zip).")
    store = _packages_dir()
    h, size = hashlib.sha256(), 0
    fd, tmp = tempfile.mkstemp(suffix=".zip", dir=store)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, f"The file is larger than {MAX_UPLOAD // 2**20} MB.")
                h.update(chunk)
                out.write(chunk)
        sha = h.hexdigest()
        existing = session.execute(select(PackageUpload).where(PackageUpload.sha256 == sha)).scalar_one_or_none()
        if existing is not None:
            return {"already_uploaded": True, **_upload_out(existing, brief=False)}
        final = store / f"{sha}.zip"
        shutil.move(tmp, final)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)

    active_v = active_package_version(session)
    review = review_package(final, _workbook_mirror(session),
                            {"version": active_v, "mappings": _package_mappings(session, active_v)})
    summary = review.get("summary", {})
    declared = summary.get("declared_version") or summary.get("filename_version") or f"upload-{sha[:8]}"
    # Never overwrite another file's catalog: a version already loaded from a different file gets a suffix.
    taken = session.execute(select(ConfigPackage.version).where(ConfigPackage.version == declared)).scalar()
    version = declared if not taken else f"{declared}+{sha[:8]}"
    up = PackageUpload(filename=file.filename, sha256=sha, size=size, stored_path=str(final), version=version,
                       declared_version=summary.get("declared_version"), release_date=summary.get("release_date"),
                       review=_jsonable(review), uploaded_by=user.label,
                       status="REVIEWED" if review.get("ok") else "REJECTED",
                       decision_note=None if review.get("ok") else "Blocking problems found by the review.")
    session.add(up)
    if review.get("ok"):
        from tools.ingestion.package import ingest_package
        ingest_package(session, final, version)
        cp = session.get(ConfigPackage, version)
        if cp is not None:
            cp.source_name = file.filename
    session.add(AuditEvent(case_id=None, actor=user.label, action="package:uploaded",
                           detail={"upload_id": up.id, "filename": file.filename, "sha256": sha, "version": version,
                                   "ok": review.get("ok"), "counts": review.get("counts")}))
    session.commit()
    return {"already_uploaded": False, **_upload_out(up, brief=False)}


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    return v


@router.get("/admin/packages/{upload_id}", tags=["packages"])
def package_detail(upload_id: str, user: CurrentUser = Depends(require_internal),
                   session: Session = Depends(get_session)) -> dict[str, Any]:
    up = session.get(PackageUpload, upload_id)
    if up is None:
        raise HTTPException(404, "No such upload.")
    return _upload_out(up, brief=False)


class Decision(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/admin/packages/{upload_id}/activate", tags=["packages"])
def activate_package(upload_id: str, body: Decision, user: CurrentUser = Depends(require_admin),
                     session: Session = Depends(get_session)) -> dict[str, Any]:
    up = session.get(PackageUpload, upload_id)
    if up is None:
        raise HTTPException(404, "No such upload.")
    if up.status == "ACTIVE":
        return _upload_out(up)
    if not (up.review or {}).get("ok"):
        raise HTTPException(409, "This beta file has blocking problems in its review and cannot be activated.")
    if up.status not in ("REVIEWED", "SUPERSEDED"):
        raise HTTPException(409, f"An upload that is {up.status} cannot be activated.")
    previous = active_upload(session)
    if previous is not None:
        previous.status = "SUPERSEDED"
    up.status, up.decided_by, up.decided_at, up.decision_note = "ACTIVE", user.label, _now(), body.note or None
    session.add(AuditEvent(case_id=None, actor=user.label, action="package:activated",
                           detail={"upload_id": up.id, "version": up.version,
                                   "previous": previous.version if previous else active_package_version(session),
                                   "note": body.note}))
    session.commit()
    return _upload_out(up)


@router.post("/admin/packages/{upload_id}/reject", tags=["packages"])
def reject_package(upload_id: str, body: Decision, user: CurrentUser = Depends(require_admin),
                   session: Session = Depends(get_session)) -> dict[str, Any]:
    up = session.get(PackageUpload, upload_id)
    if up is None:
        raise HTTPException(404, "No such upload.")
    if up.status == "ACTIVE":
        raise HTTPException(409, "Activate another beta file first; the active one cannot be rejected.")
    if not body.note.strip():
        raise HTTPException(400, "Say why the beta file is rejected.")
    up.status, up.decided_by, up.decided_at, up.decision_note = "REJECTED", user.label, _now(), body.note.strip()
    session.add(AuditEvent(case_id=None, actor=user.label, action="package:rejected",
                           detail={"upload_id": up.id, "version": up.version, "note": body.note}))
    session.commit()
    return _upload_out(up)


# --------------------------------------------------------------------------- #
# mapping explorer
# --------------------------------------------------------------------------- #

@router.get("/reference/countries", tags=["reference"])
def reference_countries(user: CurrentUser = Depends(require_internal),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
    """Every country and its groups, from both sources, marked by where they occur."""
    version = active_package_version(session)
    pkg = defaultdict(set)
    for c, g, _ in _package_mappings(session, version):
        pkg[c].add(g)
    wb = defaultdict(set)
    for c, g, _, _ in _workbook_mirror(session)["rows"]:
        wb[c].add(g)
    out = []
    for c in sorted(set(pkg) | set(wb)):
        groups = sorted(pkg[c] | wb[c])
        out.append({"country": c, "groups": [{"code": g, "in_package": g in pkg[c], "in_workbook": g in wb[c]}
                                             for g in groups]})
    return {"package_version": version, "countries": out}


def _attributes(session: Session, version: str, sir_id: str) -> list[dict[str, Any]]:
    rows = session.execute(select(SirAttribute).where(SirAttribute.package_version == version,
                                                      SirAttribute.sir_id == sir_id)
                           .order_by(SirAttribute.ent_path, SirAttribute.id)).scalars()
    return [{"att_id": a.att_id, "name": a.nm, "entity": a.ent_path, "type": a.att_ty, "mandatory": a.is_mandatory,
             "message_positions": [p.get("xPath") or p.get("jPath") for p in (a.msg_positions or [])
                                   if isinstance(p, dict)]} for a in rows]


@router.get("/reference/trace", tags=["reference"])
def trace(country: str, group: str, user: CurrentUser = Depends(require_internal),
          session: Session = Depends(get_session)) -> dict[str, Any]:
    """One requirement through both files, with a verdict per link."""
    country, group = country.strip().upper(), group.strip().upper()
    version = active_package_version(session)
    checks: list[dict[str, Any]] = []

    def check(key: str, ok: Optional[bool], title: str, detail: str) -> None:
        checks.append({"key": key, "status": "ok" if ok else ("missing" if ok is False else "na"),
                       "title": title, "detail": detail})

    # M2C workbook side
    rules = [r for r in get_reference(session).baseline_rules(country) if r.sirg_cd == group]
    wbm = _workbook_mirror(session)
    wb_rows = [r for r in wbm["rows"] if r[0] == country and r[1] == group]
    wb_sir_ids = sorted({r[2] for r in wb_rows})

    # package side
    g = session.execute(select(SirgDef).where(SirgDef.package_version == version, SirgDef.cd == group)
                        ).scalar_one_or_none() if version else None
    maps = list(session.execute(select(CtryProcMapping).where(
        CtryProcMapping.package_version == version, CtryProcMapping.ctry_cd == country,
        CtryProcMapping.sirg_id == g.id)).scalars()) if g else []
    pkg_sir_ids = sorted({m.sir_id for m in maps})
    defs = {d.id: d for d in session.execute(select(SirDef).where(
        SirDef.package_version == version, SirDef.id.in_(set(pkg_sir_ids) | set(wb_sir_ids)))).scalars()} if version else {}

    check("rule", bool(rules), "M2C Import has a rule that raises it",
          f"{len(rules)} Import row(s): {', '.join(str(r.row_no) for r in rules)}" if rules
          else f"No Import row for {country} with SIRG {group}.")
    check("workbook_mapping", bool(wb_rows), "M2C Technical SIRG maps it",
          f"{country} · {group} → {', '.join(f'{r[3]} ({r[2]})' for r in wb_rows)}" if wb_rows
          else "Not in the workbook's Technical SIRG tab.")
    check("group", g is not None, f"Package {version} has the group",
          f"{group} = {g.nm} ({g.id})" if g else f"{group} is not in the package's group list (ShpInfReqGrpDef.csv).")
    check("mapping", bool(maps) if g else False, f"Package maps it for {country}",
          f"{country} · IMP_CLR · {group} → {', '.join(pkg_sir_ids)}" if maps
          else f"No row for {country} · {group} in ShpInfReqDefInShpInfReqGrpDefOfCtryProc.csv.")
    shipped = [s for s in pkg_sir_ids if s in defs]
    check("definition", bool(shipped) if maps else False, "Package ships the definition file",
          ", ".join(f"{defs[s].cmpt_nm} — {defs[s].nm}" for s in shipped) if shipped
          else "The definition file is not in the package." if maps else "Nothing mapped, so nothing to ship.")
    if wb_rows and maps:
        same = set(wb_sir_ids) == set(pkg_sir_ids)
        check("agreement", same, "Workbook and package point at the same definition",
              "Same definition." if same else
              f"Workbook: {', '.join(wb_sir_ids)} · package: {', '.join(pkg_sir_ids)} — the workbook was updated "
              "to a definition this package does not map (a newer beta file?).")
    else:
        check("agreement", None, "Workbook and package point at the same definition", "Needs both mappings.")

    # attributes asked for by the SIR Reference bindings, resolved against the package definition
    pkg_attrs = {s: _attributes(session, version, s) for s in pkg_sir_ids} if version else {}
    by_id = {a["att_id"]: (s, a) for s, attrs in pkg_attrs.items() for a in attrs}
    bindings = []
    for r in rules:
        for b in r.bindings:
            ids = list(b.attribute_ids or [])
            bindings.append({
                "rule_row": r.row_no, "sir_id": b.sir_id, "cmpt_nm": b.cmpt_nm,
                "definition_mapped": b.sir_id in pkg_sir_ids,
                "waived_if_whitelisted": b.waived_if_whitelisted, "waived_to_validate": b.waived_to_validate,
                "check_service_code": b.check_service_code,
                "attributes": [{"att_id": a, "found": a in by_id,
                                "name": by_id[a][1]["name"] if a in by_id else None,
                                "message_positions": by_id[a][1]["message_positions"] if a in by_id else []}
                               for a in ids],
                "whole_definition": not ids,
            })
    missing_attr = sum(1 for b in bindings for a in b["attributes"] if not a["found"])
    if bindings and not pkg_sir_ids:
        check("attributes", None, "SIR Reference fields exist in the package definition",
              "Nothing mapped in the package, so the fields cannot be checked.")
    elif bindings:
        check("attributes", missing_attr == 0, "SIR Reference fields exist in the package definition",
              f"{sum(len(b['attributes']) for b in bindings)} field(s) asked for, {missing_attr} not found."
              if any(b["attributes"] for b in bindings) else "The whole definition is asked for (no field list).")

    raise_ok = all(c["status"] == "ok" for c in checks if c["key"] in ("group", "mapping", "definition"))
    return {
        "country": country, "group": group, "package_version": version, "workbook_version": wbm["version"],
        "verdict": ("CCRE can raise this requirement with the active package." if raise_ok else
                    "CCRE cannot raise this requirement with the active package — see the first ✕."),
        "can_raise": raise_ok,
        "checks": checks,
        "rules": [{"row_no": r.row_no, "shipment_type": r.shipment_type, "currency": r.currency,
                   "min_value": r.min_value, "max_value": r.max_value, "other_logic": r.other_logic} for r in rules],
        "definitions": [{"sir_id": s, "in_package_mapping": s in pkg_sir_ids, "in_workbook_mapping": s in wb_sir_ids,
                         "shipped": s in defs, "name": defs[s].nm if s in defs else None,
                         "cmpt_nm": defs[s].cmpt_nm if s in defs else None,
                         "attributes": pkg_attrs.get(s) or (_attributes(session, version, s) if s in defs else [])}
                        for s in sorted(set(pkg_sir_ids) | set(wb_sir_ids))],
        "bindings": bindings,
    }


@router.get("/reference/drift", tags=["reference"])
def drift(user: CurrentUser = Depends(require_internal), session: Session = Depends(get_session)) -> dict[str, Any]:
    """Per country: how the workbook's Technical SIRG compares with the active package."""
    version = active_package_version(session)
    pkg = defaultdict(set)
    for c, g, s in _package_mappings(session, version):
        pkg[(c, g)].add(s)
    wbm = _workbook_mirror(session)
    wb = defaultdict(set)
    for c, g, s, _ in wbm["rows"]:
        wb[(c, g)].add(s)
    per = defaultdict(lambda: {"same": 0, "differs": 0, "workbook_only": 0, "package_only": 0})
    for k in set(pkg) | set(wb):
        bucket = ("same" if wb.get(k) == pkg.get(k) else "differs") if k in pkg and k in wb else \
                 ("workbook_only" if k in wb else "package_only")
        per[k[0]][bucket] += 1
    rows = [{"country": c, **v} for c, v in sorted(per.items())]
    total = {k: sum(r[k] for r in rows) for k in ("same", "differs", "workbook_only", "package_only")}
    return {"package_version": version, "workbook_version": wbm["version"], "total": total, "countries": rows}
