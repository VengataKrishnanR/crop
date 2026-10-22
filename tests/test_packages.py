"""Beta files: upload, review, activation, the active package everywhere, and the mapping explorer."""
from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tools.package_review import review_package

ADMIN = {"X-CCRE-Role": "ADMIN"}
TEAM = {"X-CCRE-Role": "CCRE_TEAM"}
BUSINESS = {"X-CCRE-Role": "BUSINESS"}


@pytest.fixture(autouse=True)
def packages_dir(tmp_path, monkeypatch):
    """Uploaded beta files go to a temporary data folder, never the real one."""
    monkeypatch.setenv("CCRE_DATA_DIR", str(tmp_path))
    return tmp_path / "packages"


@pytest.fixture
def workbook_loaded(client: TestClient, real_workbook_path: Path) -> None:
    assert client.post("/api/ingest/workbook", json={"path": str(real_workbook_path)}).status_code == 200


def _upload(client: TestClient, path: Path, name: str | None = None, headers=ADMIN):
    with open(path, "rb") as fh:
        return client.post("/api/admin/packages", headers=headers,
                           files={"file": (name or path.name, fh, "application/zip")})


# --------------------------------------------------------------------------- #
# review
# --------------------------------------------------------------------------- #

def test_review_finds_what_a_person_found(real_package_path: Path) -> None:
    r = review_package(real_package_path)
    s = r["summary"]
    assert r["ok"] is True
    assert (s["declared_version"], s["release_date"]) == ("2.10.4-beta.2", "2025-10-21")
    assert (s["groups"], s["mappings"], s["countries"], s["definitions"]) == (83, 851, 90, 934)
    codes = {f["code"]: f for f in r["findings"]}
    assert "NEW files completed" in codes["MAPPING_NOTE_ROW"]["details"][0]          # typed note, line 853
    assert codes["MAPPING_FILENAME"]["count"] == 1                                    # RS: leading space
    assert codes["DEFINITION_UNMAPPED"]["count"] == 101
    assert "82" in codes["CHANGELOG_CLAIM_NOT_MET"]["message"]
    assert s["pending_in_changelog"]


def test_review_compares_with_the_workbook(real_package_path: Path) -> None:
    rows = [("DE", "POA", "b5a141ed-51d1-48b4-b77d-3d6eca8d64eb", "DEPOA"),
            ("MX", "IRID", "bd0fdd5f-9a13-49c2-8a26-ff088f615d3b", "IRIDMX"),
            ("BG", "IOSS", "af262af3-bbeb-495c-b3df-a74d44614566", "IOSSBG")]
    w = review_package(real_package_path, {"version": "2.10.9-beta.2", "rows": rows})["workbook"]
    assert w["same"] == 1                                                             # MX IRID
    assert any(d.startswith("DE POA") for d in w["definition_differs"])
    assert w["countries_only_in_workbook"] == ["BG"]


def test_broken_packages_are_refused(tmp_path: Path) -> None:
    bad = tmp_path / "not.zip"
    bad.write_bytes(b"not a zip")
    assert review_package(bad)["findings"][0]["code"] == "NOT_A_ZIP"
    empty = tmp_path / "sir-configuration-v.9.9.9.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("sir-configuration-v.9.9.9/README.md", "x")
        z.writestr("../evil.txt", "x")
    r = review_package(empty)
    assert not r["ok"] and {"ZIP_UNSAFE_PATHS", "MISSING_PART"} <= {f["code"] for f in r["findings"]}


# --------------------------------------------------------------------------- #
# upload and activation
# --------------------------------------------------------------------------- #

def test_upload_review_activate(client: TestClient, workbook_loaded: None, real_package_path: Path,
                               packages_dir: Path) -> None:
    up = _upload(client, real_package_path)
    assert up.status_code == 200, up.text
    u = up.json()
    assert u["status"] == "REVIEWED" and u["ok"] and u["version"] == "2.10.4-beta.2"
    assert u["workbook"]["countries_only_in_workbook"] == ["BG", "BR", "CO", "EC", "NA", "PL"]
    # Same file again: nothing new.
    again = _upload(client, real_package_path, "renamed copy.zip").json()
    assert again["already_uploaded"] and again["id"] == u["id"]
    listing = client.get("/api/admin/packages", headers=TEAM).json()
    assert listing["active_upload_id"] is None and listing["legacy_active"] is True   # loaded, not yet activated
    act = client.post(f"/api/admin/packages/{u['id']}/activate", headers=ADMIN, json={"note": "INC123"})
    assert act.status_code == 200 and act.json()["status"] == "ACTIVE"
    assert client.get("/api/admin/packages", headers=TEAM).json()["active_upload_id"] == u["id"]
    assert (packages_dir / f"{u['sha256']}.zip").exists()                         # stored by hash
    # The active one cannot be rejected; only admins upload or decide.
    assert client.post(f"/api/admin/packages/{u['id']}/reject", headers=ADMIN, json={"note": "x"}).status_code == 409
    assert _upload(client, real_package_path, headers=TEAM).status_code == 403
    assert client.get("/api/admin/packages", headers=BUSINESS).status_code == 403


def test_a_second_file_with_the_same_version_never_overwrites(client: TestClient, workbook_loaded: None,
                                                              real_package_path: Path, tmp_path: Path) -> None:
    first = _upload(client, real_package_path).json()
    client.post(f"/api/admin/packages/{first['id']}/activate", headers=ADMIN, json={})
    # Same version, different content (one mapping row dropped).
    copy = tmp_path / real_package_path.name
    with zipfile.ZipFile(real_package_path) as src, zipfile.ZipFile(copy, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.endswith("ShpInfReqDefInShpInfReqGrpDefOfCtryProc.csv"):
                lines = data.decode("utf-8-sig").splitlines()
                data = "\n".join(l for l in lines if not l.startswith("MX,")).encode()
            dst.writestr(item, data)
    second = _upload(client, copy).json()
    assert second["version"].startswith("2.10.4-beta.2+") and second["status"] == "REVIEWED"
    assert any(x.startswith("MX ") for x in second["changes_vs_active"]["removed"])
    assert "MX" in second["changes_vs_active"]["countries_removed"]
    # Activating the second switches every check; the first is kept as SUPERSEDED.
    client.post(f"/api/admin/packages/{second['id']}/activate", headers=ADMIN, json={})
    statuses = {u["id"]: u["status"] for u in client.get("/api/admin/packages", headers=ADMIN).json()["uploads"]}
    assert statuses == {first["id"]: "SUPERSEDED", second["id"]: "ACTIVE"}
    trace = client.get("/api/reference/trace?country=MX&group=IRID", headers=TEAM).json()
    assert trace["package_version"] == second["version"] and not trace["can_raise"]


def test_rejected_uploads_cannot_be_activated(client: TestClient, tmp_path: Path) -> None:
    bad = tmp_path / "sir-configuration-v.1.0.0.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("sir-configuration-v.1.0.0/README.md", "empty")
    u = _upload(client, bad).json()
    assert u["status"] == "REJECTED" and not u["ok"]
    assert client.post(f"/api/admin/packages/{u['id']}/activate", headers=ADMIN, json={}).status_code == 409
    resp = client.post("/api/admin/packages", headers=ADMIN, files={"file": ("notes.txt", io.BytesIO(b"x"), "text/plain")})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# mapping explorer and the corrected SIR Reference joins
# --------------------------------------------------------------------------- #

def test_trace_shows_each_link(client: TestClient, workbook_loaded: None, real_package_path: Path) -> None:
    u = _upload(client, real_package_path).json()
    client.post(f"/api/admin/packages/{u['id']}/activate", headers=ADMIN, json={})

    de = client.get("/api/reference/trace?country=DE&group=POA", headers=TEAM).json()
    st = {c["key"]: c["status"] for c in de["checks"]}
    assert de["can_raise"] and st["agreement"] == "missing"          # workbook moved to a newer definition
    assert {d["sir_id"][:8] for d in de["definitions"]} == {"1595f691", "b5a141ed"}

    bg = client.get("/api/reference/trace?country=BG&group=IOSS", headers=TEAM).json()
    st = {c["key"]: c["status"] for c in bg["checks"]}
    assert not bg["can_raise"] and st["rule"] == "ok" and st["workbook_mapping"] == "ok"
    assert st["group"] == "missing" and st["mapping"] == "missing"

    mx = client.get("/api/reference/trace?country=MX&group=IRID", headers=TEAM).json()
    assert mx["can_raise"] and {c["key"]: c["status"] for c in mx["checks"]}["agreement"] == "ok"
    names = [a["name"] for b in mx["bindings"] if b["rule_row"] == 41 for a in b["attributes"]]
    assert names == ["TAX ID", "CURP", "Foreigner TAX ID", "Foreigner National ID"]
    assert all(a["found"] and a["message_positions"] for b in mx["bindings"] for a in b["attributes"])

    drift = client.get("/api/reference/drift", headers=TEAM).json()
    assert drift["total"] == {"same": 717, "differs": 131, "workbook_only": 155, "package_only": 3}
    assert client.get("/api/reference/trace?country=DE&group=POA", headers=BUSINESS).status_code == 403


def test_sirg_rules_get_their_sir_reference_lines(session, real_workbook_path: Path) -> None:
    from sqlalchemy import select

    from tools.core.models import Rule
    from tools.ingestion.workbook import ingest_workbook
    res = ingest_workbook(session, real_workbook_path)
    session.commit()
    # Every rule finds its SIR Reference lines; the orphans are the 8 lines no Import rule uses.
    assert res.unbound_rules == []
    assert res.orphan_bindings == [f"SIR Reference row {r}" for r in (33, 52, 53, 54, 55, 56, 59, 60)]
    rows = {r.row_no: r for r in session.execute(select(Rule).where(Rule.rule_set_id == res.rule_set_id)).scalars()}
    assert [b.cmpt_nm for b in rows[41].bindings] == ["IRIDMX"] * 4       # by SIRG Document Reference
    assert [b.cmpt_nm for b in rows[38].bindings] == ["DEPOA"]
    assert [b.cmpt_nm for b in rows[57].bindings] == ["IOSSBG"]
    assert len(rows[4].bindings) == 2                                       # legacy: by Document Reference
