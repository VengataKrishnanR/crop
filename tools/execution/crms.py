"""CRMS API test-suite support — onboarded from ``TestSuite_CRMS`` (api-connector + proxy-server).

What came across from the suite:

* **Request sending** — POST the JSON body with the configured headers (``x-api-key``
  and ``Content-Type`` by default); hosts under ``.dhl.com`` bypass the corporate
  proxy (the suite's ``no_proxy='.dhl.com'``). See :class:`tools.execution.executor.EndpointExecutor`.
* **Response comparison** — :func:`find_differences` / :func:`extract_by_path` are
  ports of the suite's ``findDifferences`` / ``extractByPath``, used to compare one
  environment's response with another's (e.g. TEST vs UAT).

What is new here:

* :func:`build_crms_payload` adapts a ``ShpPcdDetailsMsg`` sample to one UAT test
  case (country, process type, services, B2B/B2C class, value, incoterm, …), so
  offline (stub) runs produce realistic CRMS requests. With a real model the
  ``payload_generator`` agent does this mapping.
"""
from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from tools.agents.harness.errors import GateResult

# Header sections carry per-call ids and timestamps; they always differ between calls.
VOLATILE_KEYS = frozenset({"Hdr"})


# --------------------------------------------------------------------------- #
# comparison (port of proxy-server.js)
# --------------------------------------------------------------------------- #

def extract_by_path(obj: Any, path: Optional[str]) -> Any:
    """``extractByPath``: dotted path into nested objects; None when absent."""
    if not path or obj is None:
        return obj
    result = obj
    for key in path.split("."):
        if isinstance(result, dict) and key in result:
            result = result[key]
        else:
            return None
    return result


def find_differences(a: Any, b: Any, path: str = "", ignore: frozenset[str] = frozenset()) -> list[dict]:
    """``findDifferences``: added / removed / modified leaves between two JSON values."""
    diffs: list[dict] = []
    if a is None or b is None:
        if a != b:
            diffs.append({"path": path or "root", "type": "modified", "value1": a, "value2": b})
        return diffs
    if not isinstance(a, (dict, list)) or not isinstance(b, (dict, list)):
        if a != b:
            diffs.append({"path": path or "root", "type": "modified", "value1": a, "value2": b})
        return diffs
    if isinstance(a, list) or isinstance(b, list):
        if not (isinstance(a, list) and isinstance(b, list)) or len(a) != len(b):
            diffs.append({"path": path or "root", "type": "modified",
                          "value1": f"Array[{len(a)}]" if isinstance(a, list) else a,
                          "value2": f"Array[{len(b)}]" if isinstance(b, list) else b})
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diffs.extend(find_differences(x, y, f"{path}[{i}]", ignore))
        return diffs
    for key in list(dict.fromkeys([*a.keys(), *b.keys()])):
        if key in ignore:
            continue
        new_path = f"{path}.{key}" if path else key
        if key not in a:
            diffs.append({"path": new_path, "type": "added", "value2": b[key]})
        elif key not in b:
            diffs.append({"path": new_path, "type": "removed", "value1": a[key]})
        else:
            diffs.extend(find_differences(a[key], b[key], new_path, ignore))
    return diffs


def compare_responses(body1: Any, body2: Any, path: Optional[str] = None) -> dict[str, Any]:
    """Compare two responses (optionally only at ``path``), ignoring header sections."""
    part1, part2 = extract_by_path(body1, path), extract_by_path(body2, path)
    if path and (part1 is None or part2 is None):
        missing = "first" if part1 is None else "second"
        return {"identical": False, "path": path, "differences": [],
                "summary": {"totalDifferences": 1, "added": 0, "removed": 0, "modified": 1},
                "note": f"Path '{path}' not found in the {missing} response."}
    diffs = find_differences(part1, part2, "", VOLATILE_KEYS)
    return {
        "identical": not diffs, "path": path,
        "differences": diffs[:200],
        "summary": {"totalDifferences": len(diffs),
                    "added": sum(d["type"] == "added" for d in diffs),
                    "removed": sum(d["type"] == "removed" for d in diffs),
                    "modified": sum(d["type"] == "modified" for d in diffs)},
    }


# --------------------------------------------------------------------------- #
# CRMS request (ShpPcdDetailsMsg) payload builder
# --------------------------------------------------------------------------- #

def is_crms_payload(sample: Any) -> bool:
    return isinstance(sample, dict) and "ShpPcdDetailsMsg" in sample


def _key(field: str) -> str:
    return re.sub(r"[^a-z0-9]", "", field.lower())


def _criterion(body: dict, code: str) -> Optional[dict]:
    for req in body.get("GenReq", []) or []:
        for crit in req.get("GenrcRqCritr", []) or []:
            if crit.get("@TyCd") == code:
                return crit
    return None


def _shp_class(shp: dict) -> Optional[dict]:
    for grp in shp.get("DatElGrp", []) or []:
        if grp.get("@Cd") == "ShpClss":
            for el in grp.get("DatEl", []) or []:
                if el.get("Cd") == "Clss":
                    return el
    return None


def _mon_amounts(shp: dict) -> list[dict]:
    amounts = []
    for m in shp.get("MonAmt", []) or []:
        amounts.extend(m.get("Amt", []) or [])
    for doc in shp.get("ShpDoc", []) or []:
        for m in (doc.get("CmrcInv") or {}).get("MonAmt", []) or []:
            amounts.extend(m.get("Amt", []) or [])
    return amounts


def build_crms_payload(sample: dict, test_case: dict, country: str,
                       direction: str = "Import") -> dict[str, Any]:
    """Adapt a ``ShpPcdDetailsMsg`` sample to one test case. Returns payload/changes/assumptions."""
    payload = copy.deepcopy(sample)
    body = payload["ShpPcdDetailsMsg"].setdefault("Bd", {})
    shipments = body.get("Shp") or [{}]
    shp = shipments[0]
    changes: list[dict] = []
    assumptions: list[str] = []
    test_id = test_case.get("test_id") or "UAT"
    country = country.upper()

    def note(path: str, value: Any, reason: str) -> None:
        changes.append({"path": path, "value": value, "reason": reason})

    # Who and what is being evaluated
    crit = _criterion(body, "CtryCd")
    if crit is not None:
        crit["Val"] = [country]
        note("Bd.GenReq[0].GenrcRqCritr[CtryCd].Val", [country], "country under onboarding")
    proc = _criterion(body, "ProcTy")
    if proc is not None:
        proc["Val"] = [direction]
        note("Bd.GenReq[0].GenrcRqCritr[ProcTy].Val", [direction], "clearance direction")
    if direction == "Import":
        shp["DstCtryCd"] = country
        note("Bd.Shp[0].DstCtryCd", country, "import into the country under onboarding")
    else:
        shp["OrgCtryCd"] = country
        note("Bd.Shp[0].OrgCtryCd", country, "export from the country under onboarding")
    for ref in shp.get("ShpRef", []) or []:
        if ref.get("@TyCd") == "UCI":
            ref["Ref"] = f"UAT-{test_id}"
            note("Bd.Shp[0].ShpRef[UCI].Ref", ref["Ref"], "unique reference per test case")

    for cond in test_case.get("input_conditions") or []:
        field, op, value = str(cond.get("field") or ""), str(cond.get("operator") or ""), cond.get("value")
        key, reason = _key(field), f"{field} {op} {'' if value is None else value}".strip()
        negative = op in {"not_contains", "not_equals", "absent"}

        if key in {"servicecode", "servicecodes", "servicecodelist"}:
            code = str(value or "").upper()
            services = shp.setdefault("Srv", [])
            present = [s for s in services if (s.get("GlSrvCd") or {}).get("$", "").upper() == code]
            if negative:
                shp["Srv"] = [s for s in services if s not in present]
            elif not present:
                services.append({"Chrg": [{"ObChrgDstBInd": "N", "OInd": "N"}],
                                 "GlSrvCd": {"$": code, "@GlProdSrvClssCd": "S"}})
            note("Bd.Shp[0].Srv[].GlSrvCd", [s["GlSrvCd"]["$"] for s in shp["Srv"]], reason)
        elif key in {"shipmenttype", "type"}:
            el = _shp_class(shp)
            wanted = str(value).split("/")[0]
            if negative:
                wanted = "B2B" if wanted.upper() == "B2C" else "B2C"
            if el is None:
                shp.setdefault("DatElGrp", []).append(
                    {"@Cd": "ShpClss", "DatEl": [{"Cd": "ClssTy", "Val": {"$": "ShpTrTyClss"}},
                                                 {"Cd": "Clss", "Val": {"$": wanted}}]})
            else:
                el["Val"] = {"$": wanted}
            note("Bd.Shp[0].DatElGrp[ShpClss].Clss", wanted, reason)
        elif key in {"value", "declaredvalue", "shipmentvalue", "customsvalue"}:
            try:
                amount = float(value)
            except (TypeError, ValueError):
                assumptions.append(f"Could not use '{value}' as a value for {field}.")
                continue
            for amt in _mon_amounts(shp):
                amt["$"] = amount
            note("Bd.Shp[0].MonAmt / CmrcInv.MonAmt", amount, reason)
        elif key == "currency":
            for amt in _mon_amounts(shp):
                amt["@CurCd"] = str(value).upper()
            note("Bd.Shp[0].MonAmt[].@CurCd", str(value).upper(), reason)
        elif key in {"incoterm", "incoterms", "incotermcode"}:
            wanted = str(value).upper()
            if negative:
                wanted = "DAP" if wanted != "DAP" else "EXW"
            for doc in shp.get("ShpDoc", []) or []:
                doc.setdefault("CmrcInv", {})["IncTrmCd"] = wanted
            note("Bd.Shp[0].ShpDoc[].CmrcInv.IncTrmCd", wanted, reason)
        elif key in {"origincountry", "origin"}:
            wanted = str(value).upper()
            if negative:
                wanted = "CN" if wanted != "CN" else "US"
            shp["OrgCtryCd"] = wanted
            note("Bd.Shp[0].OrgCtryCd", wanted, reason)
        elif key in {"destinationservicearea", "servicearea"}:
            wanted = "XXX" if negative else str(value).upper()
            shp["DstSrvACd"] = wanted
            note("Bd.Shp[0].DstSrvACd", wanted, reason)
        elif key in {"weight", "weightkg"}:
            for m in shp.get("Meas", []) or []:
                if m.get("@TyCd") == "DEC" and "Wgt" in m:
                    m["Wgt"]["$"] = f"{float(value):.2f}"
            note("Bd.Shp[0].Meas[DEC].Wgt", value, reason)
        else:
            assumptions.append(f"No field in the CRMS request is mapped for '{reason}'; "
                               "the sample value was kept. Map it with the AI generator or extend crms.py.")

    shipments[0] = shp
    body["Shp"] = shipments
    return {"payload": payload, "changes": changes, "assumptions": assumptions}


# --------------------------------------------------------------------------- #
# structural validation (gate; docs/adr/0002)
# --------------------------------------------------------------------------- #

_CTRY = re.compile(r"^[A-Z]{2}$")
_CUR = re.compile(r"^[A-Z]{3}$")
_INCOTERM = re.compile(r"^[A-Z]{3}$")
_ROOT = "ShpPcdDetailsMsg"


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_crms_payload(payload: Any, country: Optional[str] = None,
                          direction: Optional[str] = None) -> "GateResult":
    """Structural checks on a ``ShpPcdDetailsMsg`` request before it is sent.

    Not a CRMS schema: it checks what :func:`build_crms_payload` sets and what a
    test depends on -- the message skeleton, the country criterion and shipment
    countries, amounts, currencies, weights, shipment class and incoterm. When
    ``country`` / ``direction`` are given they must match the message.
    """
    from tools.agents.harness.errors import GateError, GateResult

    errors: list[GateError] = []

    def err(code: str, path: str, message: str, hint: str) -> None:
        errors.append(GateError(code=code, path=path, message=message, hint=hint))

    if not is_crms_payload(payload) or not isinstance(payload[_ROOT], dict):
        err("CRMS_ROOT", _ROOT, "The request is not a ShpPcdDetailsMsg message.",
            "Start from the endpoint's sample request; only field values may change.")
        return GateResult.from_errors(errors)
    body = payload[_ROOT].get("Bd")
    if not isinstance(body, dict):
        err("CRMS_BODY", f"{_ROOT}.Bd", "The message has no body (Bd).", "Keep the sample's Bd section.")
        return GateResult.from_errors(errors)
    shipments = body.get("Shp")
    if not isinstance(shipments, list) or not shipments or not isinstance(shipments[0], dict):
        err("CRMS_SHIPMENT", f"{_ROOT}.Bd.Shp", "The message has no shipment (Bd.Shp[0]).",
            "Keep the sample's Bd.Shp list with one shipment.")
        return GateResult.from_errors(errors)
    shp = shipments[0]
    sp = f"{_ROOT}.Bd.Shp[0]"
    want_country = country.upper() if country else None

    crit = _criterion(body, "CtryCd")
    cpath = f"{_ROOT}.Bd.GenReq[0].GenrcRqCritr[CtryCd].Val"
    values = (crit or {}).get("Val") if crit else None
    if not isinstance(values, list) or len(values) != 1 or not _CTRY.match(str(values[0])):
        err("CRMS_COUNTRY", cpath, "The country criterion must hold exactly one ISO-2 country code.",
            f"Set it to [\"{want_country or 'XX'}\"].")
    elif want_country and values[0] != want_country:
        err("CRMS_COUNTRY_MISMATCH", cpath, f"The country criterion is {values[0]}, not the country under "
            f"test {want_country}.", f"Set it to [\"{want_country}\"].")

    proc = _criterion(body, "ProcTy")
    proc_val = ((proc or {}).get("Val") or [None])[0] if proc else None
    if proc is not None and proc_val not in ("Import", "Export"):
        err("CRMS_DIRECTION", f"{_ROOT}.Bd.GenReq[0].GenrcRqCritr[ProcTy].Val",
            f"Process type {proc_val!r} is not Import or Export.", "Use [\"Import\"] or [\"Export\"].")
    direction = direction or proc_val
    for key in ("DstCtryCd", "OrgCtryCd"):
        if key in shp and not _CTRY.match(str(shp[key] or "")):
            err("CRMS_CTRY_FORMAT", f"{sp}.{key}", f"{key} {shp[key]!r} is not an ISO-2 country code.",
                "Use two upper-case letters, e.g. DE.")
    if want_country and direction in ("Import", "Export"):
        key = "DstCtryCd" if direction == "Import" else "OrgCtryCd"
        if shp.get(key) != want_country:
            err("CRMS_COUNTRY_MISMATCH", f"{sp}.{key}", f"{direction} into/out of {want_country} needs "
                f"{key} = {want_country}; found {shp.get(key)!r}.", f"Set {key} to {want_country}.")

    amount_lists: list[tuple[str, Any]] = [(f"{sp}.MonAmt[{i}]", m) for i, m in enumerate(shp.get("MonAmt") or [])]
    for k, doc in enumerate(shp.get("ShpDoc") or []):
        inv = (doc or {}).get("CmrcInv") or {}
        amount_lists += [(f"{sp}.ShpDoc[{k}].CmrcInv.MonAmt[{i}]", m) for i, m in enumerate(inv.get("MonAmt") or [])]
        if "IncTrmCd" in inv and not _INCOTERM.match(str(inv["IncTrmCd"] or "")):
            err("CRMS_INCOTERM", f"{sp}.ShpDoc[{k}].CmrcInv.IncTrmCd",
                f"Incoterm {inv['IncTrmCd']!r} is not a 3-letter code.", "Use e.g. DAP or DDP.")
    for base, mon in amount_lists:
        for j, amt in enumerate((mon or {}).get("Amt") or []):
            value = _number((amt or {}).get("$"))
            if value is None or value < 0:
                err("CRMS_AMOUNT", f"{base}.Amt[{j}].$", f"Amount {(amt or {}).get('$')!r} is not a "
                    "non-negative number.", "Write the amount as a number, e.g. 150.01.")
            if not _CUR.match(str((amt or {}).get("@CurCd") or "")):
                err("CRMS_CURRENCY", f"{base}.Amt[{j}].@CurCd", f"Currency {(amt or {}).get('@CurCd')!r} is "
                    "not an ISO-4217 code.", "Use three upper-case letters, e.g. EUR.")

    for i, m in enumerate(shp.get("Meas") or []):
        if (m or {}).get("@TyCd") == "DEC" and "Wgt" in m:
            value = _number((m["Wgt"] or {}).get("$"))
            if value is None or value < 0:
                err("CRMS_WEIGHT", f"{sp}.Meas[{i}].Wgt.$", f"Weight {(m['Wgt'] or {}).get('$')!r} is not a "
                    "non-negative number.", "Write the weight in kg, e.g. \"2.50\".")

    el = _shp_class(shp)
    if el is not None:
        clss = ((el.get("Val") or {}).get("$") if isinstance(el.get("Val"), dict) else None)
        if clss not in ("B2B", "B2C"):
            err("CRMS_CLASS", f"{sp}.DatElGrp[ShpClss].Clss", f"Shipment class {clss!r} is not B2B or B2C.",
                "Use B2B or B2C.")
    for i, srv in enumerate(shp.get("Srv") or []):
        if not str(((srv or {}).get("GlSrvCd") or {}).get("$") or "").strip():
            err("CRMS_SERVICE", f"{sp}.Srv[{i}].GlSrvCd.$", "A service entry has no service code.",
                "Remove the entry or give it a code, e.g. DD.")
    return GateResult.from_errors(errors)
