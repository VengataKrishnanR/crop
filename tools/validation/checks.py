"""The check register.

Every check is ``(Snapshot) -> list[Finding]`` and registered by code. Adding a
check is adding a function; nothing else changes. Severity policy:

* **blocker** -- the rule set cannot be tested or released as it stands.
* **caution** -- a human must look and accept; sign-off records the acceptance.
* **info** -- recorded for the evidence pack, no action implied.
"""
from __future__ import annotations

from collections import Counter
from typing import Callable

from tools.core import grammar
from .report import Finding, sample
from .snapshot import Snapshot

CheckFn = Callable[[Snapshot], list[Finding]]

REGISTRY: dict[str, CheckFn] = {}
DESCRIPTIONS: dict[str, str] = {}


def check(code: str, description: str) -> Callable[[CheckFn], CheckFn]:
    def wrap(fn: CheckFn) -> CheckFn:
        REGISTRY[code] = fn
        DESCRIPTIONS[code] = description
        return fn
    return wrap


# --------------------------------------------------------------------------- #
# Cross-artifact drift: workbook mirror versus package
# --------------------------------------------------------------------------- #

@check("CHK001", "Workbook SIRG mirror agrees with the package country mapping")
def chk_mapping_drift(snap: Snapshot) -> list[Finding]:
    if not snap.mirror_sirg or not snap.mappings:
        return []
    mirror = {
        (m.ctry_cd or "", m.proc_lvl_cd or "", m.sirg_id or "", m.sir_id or "")
        for m in snap.mirror_sirg
    }
    only_workbook = mirror - snap.mappings
    only_package = snap.mappings - mirror
    matched = len(mirror & snap.mappings)

    out: list[Finding] = []
    if only_workbook:
        countries = Counter(k[0] for k in only_workbook)
        out.append(Finding(
            code="CHK001", severity="caution",
            where=f"workbook {snap.workbook_version} vs package {snap.package_version}",
            message=(
                f"{len(only_workbook)} country/SIRG/SIR rows exist in the workbook but not in the "
                f"package. The workbook is ahead of, or diverged from, the source of truth."
            ),
            evidence="Most affected: " + ", ".join(f"{c}:{n}" for c, n in countries.most_common(8)),
            counts={"matched": matched, "workbook_only": len(only_workbook), "package_only": len(only_package)},
        ))
    if only_package:
        countries = Counter(k[0] for k in only_package)
        out.append(Finding(
            code="CHK001", severity="caution",
            where=f"package {snap.package_version} vs workbook {snap.workbook_version}",
            message=(
                f"{len(only_package)} rows exist in the package but are missing from the workbook. "
                f"Rules for these have not been authored."
            ),
            evidence="Most affected: " + ", ".join(f"{c}:{n}" for c, n in countries.most_common(8)),
            counts={"matched": matched, "workbook_only": len(only_workbook), "package_only": len(only_package)},
        ))
    return out


@check("CHK002", "Every referenced requirement group exists in the package catalogue")
def chk_sirg_exists(snap: Snapshot) -> list[Finding]:
    if not snap.sirg_by_id:
        return []
    unknown: dict[str, str] = {}
    for row in snap.mirror_sirg:
        if row.sirg_id and row.sirg_id not in snap.sirg_by_id:
            unknown[row.sirg_id] = row.sirg_cd or "?"
    for rule in snap.rules:
        for binding in rule.bindings:
            if binding.sirg_id and binding.sirg_id not in snap.sirg_by_id:
                unknown[binding.sirg_id] = binding.sirg_cd or "?"
    if not unknown:
        return []
    codes = sorted(set(unknown.values()))
    return [Finding(
        code="CHK002", severity="blocker",
        where="package · ShpInfReqGrpDef.csv",
        message=(
            f"{len(unknown)} requirement group id(s) are referenced but not defined in the package "
            f"catalogue: {', '.join(codes)}."
        ),
        evidence=f"The catalogue defines {len(snap.sirg_by_id)} groups.",
        subjects=sample(unknown.keys()),
    )]


@check("CHK003", "Every referenced requirement definition is shipped by the package")
def chk_sir_exists(snap: Snapshot) -> list[Finding]:
    if not snap.sir_by_id:
        return []
    missing: set[str] = set()
    for row in snap.mirror_sir:
        if row.sir_id and row.sir_id not in snap.sir_by_id:
            missing.add(row.sir_id)
    rule_missing: set[str] = set()
    for rule in snap.rules:
        for binding in rule.bindings:
            if binding.sir_id and binding.sir_id not in snap.sir_by_id:
                rule_missing.add(binding.sir_id)

    out: list[Finding] = []
    if rule_missing:
        out.append(Finding(
            code="CHK003", severity="blocker",
            where="package · sir definitions",
            message=(
                f"{len(rule_missing)} requirement definition(s) bound by rules under review are not "
                f"present in the package. CCRE cannot evaluate these rules until the package ships them."
            ),
            evidence="Support must rebuild and upload the package before testing.",
            subjects=sample(rule_missing),
        ))
    only_mirror = missing - rule_missing
    if only_mirror:
        out.append(Finding(
            code="CHK003", severity="caution",
            where="workbook mirror vs package",
            message=(
                f"{len(only_mirror)} definition id(s) appear in the workbook's catalogue mirror but "
                f"are not shipped by the package."
            ),
            evidence=f"The package ships {len(snap.sir_by_id)} definitions.",
            subjects=sample(only_mirror),
        ))
    return out


@check("CHK004", "Shipped definitions are reachable from the country mapping")
def chk_unmapped_definitions(snap: Snapshot) -> list[Finding]:
    if not snap.sir_by_id or not snap.mappings:
        return []
    unmapped = set(snap.sir_by_id) - snap.active_sir_ids
    if not unmapped:
        return []
    named = [f"{snap.sir_by_id[s].nm}" for s in sorted(unmapped)[:6]]
    return [Finding(
        code="CHK004", severity="info",
        where="package · sir definitions",
        message=(
            f"{len(unmapped)} shipped definition(s) are not referenced by any country mapping, so they "
            f"are inactive. No status field exists, so reachability is the only test."
        ),
        evidence="Examples: " + "; ".join(named),
        subjects=sample(unmapped),
        counts={"shipped": len(snap.sir_by_id), "active": len(snap.active_sir_ids), "inactive": len(unmapped)},
    )]


@check("CHK005", "Bound attribute ids resolve inside their definition")
def chk_attribute_ids(snap: Snapshot) -> list[Finding]:
    bad: list[str] = []
    checked = 0
    for rule in snap.rules:
        for binding in rule.bindings:
            if not binding.sir_id or binding.sir_id not in snap.sir_by_id:
                continue
            known = snap.attributes_by_sir.get(binding.sir_id, set())
            for att in binding.attribute_ids or []:
                checked += 1
                if att not in known:
                    bad.append(f"{binding.sir_id[:8]}→{att}")
    if not bad:
        return []
    return [Finding(
        code="CHK005", severity="blocker",
        where="rule bindings · attribute ids",
        message=f"{len(bad)} bound attribute id(s) do not exist in the referenced definition.",
        evidence=f"{checked} attribute references checked, walking Ent[] recursively.",
        subjects=sample(bad),
    )]


@check("CHK006", "Requirement group code and name agree across artifacts")
def chk_sirg_text(snap: Snapshot) -> list[Finding]:
    out: list[Finding] = []
    mismatched: list[str] = []
    for row in snap.mirror_sirg:
        catalogue = snap.sirg_by_id.get(row.sirg_id or "")
        if not catalogue:
            continue
        if (row.sirg_cd or "") != catalogue.cd:
            mismatched.append(f"{row.sirg_id[:8]}: workbook {row.sirg_cd!r} vs package {catalogue.cd!r}")
        elif (row.sirg_nm or "") != (catalogue.nm or ""):
            mismatched.append(f"{catalogue.cd}: name differs")
    if mismatched:
        out.append(Finding(
            code="CHK006", severity="caution",
            where="workbook mirror vs package catalogue",
            message=f"{len(set(mismatched))} requirement group(s) disagree on code or name.",
            evidence="; ".join(sorted(set(mismatched))[:6]),
        ))
    return out


@check("CHK007", "Definition component, name and description agree across artifacts")
def chk_sir_text(snap: Snapshot) -> list[Finding]:
    cmpt: list[str] = []
    text: list[str] = []
    whitespace = 0
    for row in snap.mirror_sir:
        shipped = snap.sir_by_id.get(row.sir_id)
        if not shipped:
            continue
        if (row.cmpt_nm or "") != (shipped.cmpt_nm or ""):
            cmpt.append(f"{row.sir_id[:8]}: {row.cmpt_nm!r} vs {shipped.cmpt_nm!r}")
        for mine, theirs in ((row.nm, shipped.nm), (row.dsc, shipped.dsc)):
            a, b = (mine or ""), (theirs or "")
            if a != b:
                if a.strip() == b.strip():
                    whitespace += 1
                else:
                    text.append(f"{row.sir_id[:8]}: {a!r} vs {b!r}")

    out: list[Finding] = []
    if cmpt:
        out.append(Finding(
            code="CHK007", severity="blocker",
            where="workbook mirror vs package",
            message=f"{len(cmpt)} definition(s) disagree on component name, which is a binding key.",
            evidence="; ".join(cmpt[:6]),
        ))
    if text:
        out.append(Finding(
            code="CHK007", severity="caution",
            where="workbook mirror vs package",
            message=f"{len(text)} definition name/description value(s) differ in substance.",
            evidence="; ".join(text[:6]),
        ))
    if whitespace:
        out.append(Finding(
            code="CHK007", severity="info",
            where="workbook mirror vs package",
            message=f"{whitespace} name/description value(s) differ only by surrounding whitespace.",
            evidence="Export normalises whitespace, so these resolve on the next package build.",
        ))
    return out


@check("CHK008", "No duplicate country/group/definition rows")
def chk_duplicates(snap: Snapshot) -> list[Finding]:
    counter = Counter(
        (m.ctry_cd or "", m.proc_lvl_cd or "", m.sirg_id or "", m.sir_id or "")
        for m in snap.mirror_sirg
    )
    dupes = {k: v for k, v in counter.items() if v > 1}
    if not dupes:
        return []
    listed = [f"{k[0]} {k[2][:8]}/{k[3][:8]} ×{v}" for k, v in list(dupes.items())[:6]]
    return [Finding(
        code="CHK008", severity="caution",
        where="workbook · Technical SIRG",
        message=f"{len(dupes)} duplicate country/group/definition row(s).",
        evidence="; ".join(listed),
    )]


# --------------------------------------------------------------------------- #
# Rule-level checks
# --------------------------------------------------------------------------- #

@check("CHK009", "Rules and their requirement bindings resolve both ways")
def chk_binding_integrity(snap: Snapshot) -> list[Finding]:
    out: list[Finding] = []
    unbound = [r for r in snap.rules if not r.bindings]
    placeholders = [
        r for r in snap.rules
        if r.doc_reference and set(r.doc_reference.split("|")) == {"TEST"}
    ]
    if unbound:
        real = [r for r in unbound if r not in placeholders]
        if real:
            out.append(Finding(
                code="CHK009", severity="blocker",
                where="rules · requirement binding",
                message=f"{len(real)} rule(s) raise no requirement, so matching them has no effect.",
                evidence="; ".join(f"{r.ctry_cd} row {r.row_no}" for r in real[:6]),
                subjects=[r.id for r in real[:8]],
            ))
    if placeholders:
        out.append(Finding(
            code="CHK009", severity="caution",
            where="rules · reference key",
            message=f"{len(placeholders)} rule(s) still carry the TEST placeholder reference key.",
            evidence="These were never bound to a real requirement group.",
            subjects=[r.id for r in placeholders[:8]],
        ))
    return out


@check("CHK010", "Rule expressions parse and are free of logic traps")
def chk_expressions(snap: Snapshot) -> list[Finding]:
    out: list[Finding] = []
    for rule in snap.rules:
        if not rule.other_logic:
            continue
        for diag in grammar.analyse(rule.other_logic):
            out.append(Finding(
                code=f"CHK010/{diag.code}",
                severity="blocker" if diag.severity == "error" else "caution",
                where=f"rule · {rule.ctry_cd} {rule.sirg_cd or ''} · Other Logic".strip(),
                message=diag.message,
                evidence=rule.other_logic,
                subjects=[rule.id],
            ))
    return out


@check("CHK011", "Expression palette matches the syntax live rules require")
def chk_template_syntax(snap: Snapshot) -> list[Finding]:
    bad: list[str] = []
    for template in snap.templates:
        diags = grammar.analyse(template)
        if any(d.severity == "error" for d in diags):
            reasons = "; ".join(d.message for d in diags if d.severity == "error")
            bad.append(f"{template.strip()[:60]} — {reasons}")
    if not bad:
        return []
    return [Finding(
        code="CHK011", severity="caution",
        where="workbook · Other Logic palette",
        message=(
            f"{len(bad)} palette expression(s) would not parse if copied into a rule. Authors copying "
            f"from the palette produce invalid logic."
        ),
        evidence=" | ".join(bad[:4]),
    )]


@check("CHK012", "Rule field values are within their permitted lists")
def chk_permitted_values(snap: Snapshot) -> list[Finding]:
    if not snap.permitted:
        return []
    out: list[Finding] = []
    offences: dict[str, set[str]] = {}
    pairs = (
        ("currency", lambda r: r.currency),
        ("region", lambda r: r.region),
        ("shipment_type", lambda r: r.shipment_type),
        ("value_basis", lambda r: r.value_basis),
    )
    for field_name, getter in pairs:
        allowed = snap.permitted.get(field_name)
        if not allowed:
            continue
        for rule in snap.rules:
            value = getter(rule)
            if value and value not in allowed:
                offences.setdefault(field_name, set()).add(f"{value} ({rule.ctry_cd})")
    for field_name, values in offences.items():
        allowed = sorted(snap.permitted.get(field_name, set()))
        out.append(Finding(
            code="CHK012", severity="caution",
            where=f"rules · {field_name}",
            message=f"{len(values)} value(s) for {field_name} are not in the permitted list: "
                    f"{', '.join(sorted(values))}.",
            evidence=f"Permitted: {', '.join(allowed)}.",
        ))
    return out


@check("CHK013", "Package release notes are reflected in the rule layer")
def chk_release_notes(snap: Snapshot) -> list[Finding]:
    if not snap.release_entries:
        return []
    mirror_ids = {m.sir_id for m in snap.mirror_sir if m.sir_id}
    if not mirror_ids:
        return []
    absent = [e for e in snap.release_entries if e.sir_id not in mirror_ids]
    if not absent:
        return []
    listed = [f"{e.ctry_cd} {e.sirg_cd}" for e in absent[:10]]
    return [Finding(
        code="CHK013", severity="caution",
        where=f"package {snap.package_version} · Release-Notes.md",
        message=(
            f"{len(absent)} requirement(s) announced by the package release notes are absent from the "
            f"rule layer, so the shipped definitions are unused."
        ),
        evidence="Missing: " + ", ".join(listed),
        subjects=[e.sir_id for e in absent[:8]],
    )]


@check("CHK014", "Threshold rules declare a value band")
def chk_value_band(snap: Snapshot) -> list[Finding]:
    suspect = [
        r for r in snap.rules
        if r.value_basis in {"DV", "IV"} and r.min_value is None and r.max_value is None
    ]
    if not suspect:
        return []
    return [Finding(
        code="CHK014", severity="info",
        where="rules · value band",
        message=(
            f"{len(suspect)} rule(s) declare a value basis but no minimum or maximum, so they apply at "
            f"any value. Intended only where the requirement is value-independent."
        ),
        evidence="; ".join(f"{r.ctry_cd} {r.sirg_cd or ''} row {r.row_no}".strip() for r in suspect[:6]),
        subjects=[r.id for r in suspect[:8]],
    )]


@check("CHK015", "Rule countries are present in the package")
def chk_country_in_package(snap: Snapshot) -> list[Finding]:
    if not snap.mappings:
        return []
    mapped = snap.mapped_countries
    missing = sorted({r.ctry_cd for r in snap.rules if r.ctry_cd and r.ctry_cd not in mapped})
    if not missing:
        return []
    return [Finding(
        code="CHK015", severity="blocker",
        where=f"package {snap.package_version} · country mapping",
        message=(
            f"{len(missing)} country/countries have rules but no mapping rows in the package: "
            f"{', '.join(missing)}. CCRE will not raise their requirements."
        ),
        evidence="Request a package rebuild from Support before testing.",
        subjects=missing,
    )]


@check("CHK016", "Reference keys follow the generated convention")
def chk_doc_reference(snap: Snapshot) -> list[Finding]:
    drifted: list[str] = []
    for rule in snap.rules:
        if not rule.doc_reference:
            continue
        if set(rule.doc_reference.split("|")) == {"TEST"}:
            continue
        if rule.doc_reference != rule.generated_doc_reference:
            drifted.append(
                f"{rule.ctry_cd} row {rule.row_no}: {rule.doc_reference!r} "
                f"vs generated {rule.generated_doc_reference!r}"
            )
    if not drifted:
        return []
    return [Finding(
        code="CHK016", severity="caution",
        where="rules · Document Reference",
        message=(
            f"{len(drifted)} reference key(s) were hand-typed and do not match the generated "
            f"country|direction|countryHold|globalHold form."
        ),
        evidence="; ".join(drifted[:5]) + ". Export regenerates these, which removes the drift.",
    )]
