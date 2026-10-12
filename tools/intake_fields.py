"""The M2C criteria a business requirement must state — one per Import column.

Requirement gathering (form, NLP and chat) collects exactly the columns the CCRE
team needs to write the M2C row:

    Region · Country · B2B/B2C · Effective Date · Date of Expiry · Network Product
    Code · Declared/Intrinsic Value · Currency · Min Value · Max Value ·
    Weight (>=) · Weight (<=) · Other Logic   (+ the requirement group to raise)

This module is the single source of truth for them: what each field accepts
(shown to the user next to the field), how to read it from plain text, how to
check it, which question to ask when it is missing, and how it becomes an M2C
Import row. It is deterministic — the language model may help phrase, but
completeness and acceptance are decided here.

Criteria shape (``structured["m2c"]``)::

    {"region": "EU", "country": "BG", "shipment_type": "B2C",
     "effective_date": "2026-11-15", "expiry_date": "N/A",
     "network_product_codes": ["P", "Y"] | "N/A",
     "value_basis": "DV", "currency": "EUR",
     "min_value": {"op": ">", "value": 150} | "N/A", "max_value": ...,
     "min_weight": ..., "max_weight": ..., "other_logic": "..." | "N/A",
     "requirement_groups": ["IOSS"]}

``None`` / absent = not answered yet (a question is asked); ``"N/A"`` = the user
said it does not apply (e.g. no expiry, all products, no value band).
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from typing import Any, Optional

NA = "N/A"

MIN_OPS = (">=", ">", "=")
MAX_OPS = ("<=", "<", "=")
STRICT_STEP = 0.01       # how the workbook writes strict bounds: "> 50" is Min 50.01

COMMON_CURRENCIES = (
    "EUR", "USD", "GBP", "BGN", "CHF", "CZK", "DKK", "HUF", "NOK", "PLN", "RON", "SEK", "ISK", "TRY",
    "AED", "BHD", "KWD", "OMR", "QAR", "SAR", "ILS", "EGP", "ZAR", "CNY", "HKD", "INR", "JPY", "KRW",
    "SGD", "AUD", "NZD", "CAD", "MXN", "BRL",
)

# Order = the M2C Import columns, then the requirement group.
FIELDS: list[dict[str, Any]] = [
    {"key": "region", "label": "Region", "kind": "choice", "required": True,
     "question": "Which region is the country in?",
     "accepted": "One region code from the workbook's Region list."},
    {"key": "country", "label": "Country", "kind": "country", "required": True,
     "question": "Which country is it for?",
     "accepted": "The onboarding's country (ISO two-letter code). Fixed for this onboarding."},
    {"key": "shipment_type", "label": "B2B/B2C", "kind": "choice", "required": True,
     "question": "Does it apply to business (B2B), consumer (B2C) shipments, or both (B2B/B2C)?",
     "accepted": "B2B, B2C or B2B/B2C."},
    {"key": "effective_date", "label": "Effective Date (DD-MM-YYYY)", "kind": "date", "required": True,
     "question": "From which date must the rule be effective? (DD-MM-YYYY)",
     "accepted": "A date, DD-MM-YYYY (e.g. 15-11-2026). Cannot be after the expiry date."},
    {"key": "expiry_date", "label": "Date of Expiry (DD-MM-YYYY)", "kind": "date", "required": False,
     "question": "Does the rule expire? Give the date (DD-MM-YYYY), or say 'no expiry'.",
     "accepted": "A date, DD-MM-YYYY, on or after the effective date — or 'No expiry'."},
    {"key": "network_product_codes", "label": "Network Product Code", "kind": "multi", "required": False,
     "question": "Which network product codes does it apply to? Comma-separated (e.g. P, Y, H), or 'all products'.",
     "accepted": "One or more product codes, comma-separated (letters/digits, e.g. P, Y, 8). "
                 "Pick from the list or add your own — or 'All products'."},
    {"key": "value_basis", "label": "Declared Value / Intrinsic Value", "kind": "choice", "required": False,
     "question": "Is the value limit on the declared value (DV) or the intrinsic value (IV)?",
     "accepted": "DV (declared value) or IV (intrinsic value). Needed when a value limit is given."},
    {"key": "currency", "label": "Currency", "kind": "currency", "required": False,
     "question": "In which currency are the value limits? (e.g. EUR)",
     "accepted": "A three-letter ISO currency code (e.g. EUR, USD, BGN). Needed when a value limit is given."},
    {"key": "min_value", "label": "Min Value", "kind": "bound", "side": "min", "unit": "value", "required": False,
     "question": "Is there a minimum shipment value? e.g. '> 150' or '>= 150', or 'none'.",
     "accepted": "An operator (>=, > or =) and a number ≥ 0, e.g. > 150. "
                 "M2C stores minimums as '>=': '> 150' is written as 150.01. Or 'No minimum'."},
    {"key": "max_value", "label": "Max Value", "kind": "bound", "side": "max", "unit": "value", "required": False,
     "question": "Is there a maximum shipment value? e.g. '<= 150' or '< 150', or 'none'.",
     "accepted": "An operator (<=, < or =) and a number ≥ 0, not below the minimum, e.g. <= 150. "
                 "M2C stores maximums as '<=': '< 150' is written as 149.99. Or 'No maximum'."},
    {"key": "min_weight", "label": "Shipment Weight kg (min)", "kind": "bound", "side": "min", "unit": "kg",
     "required": False, "question": "Is there a minimum shipment weight in kg? e.g. '> 2', or 'none'.",
     "accepted": "An operator (>=, > or =) and a weight in kg ≥ 0, e.g. >= 2. Or 'No minimum'."},
    {"key": "max_weight", "label": "Shipment Weight kg (max)", "kind": "bound", "side": "max", "unit": "kg",
     "required": False, "question": "Is there a maximum shipment weight in kg? e.g. '<= 30', or 'none'.",
     "accepted": "An operator (<=, < or =) and a weight in kg ≥ 0, not below the minimum. Or 'No maximum'."},
    {"key": "other_logic", "label": "Other Logic", "kind": "text", "required": False,
     "question": "Any other condition? e.g. 'SDT is present', 'service code is not DD', 'incoterm DDP' — or 'none'.",
     "accepted": "Your condition in your own words or as an expression, e.g. SDT present and no DD — "
                 "or !serviceCodeList.contains(\"DD\"). Plain words are fine: the CCRE team converts them. Or 'None'."},
    {"key": "requirement_groups", "label": "Requirement to raise (group)", "kind": "groups", "required": True,
     "question": "Which document / requirement group must be requested? (e.g. IOSS, POAB)",
     "accepted": "One or more requirement group codes (e.g. IOSS, POAB, POA), comma-separated."},
]
FIELD_BY_KEY = {f["key"]: f for f in FIELDS}
M2C_KEYS = [f["key"] for f in FIELDS if f["key"] != "requirement_groups"]
_ASK_ORDER = ["region", "shipment_type", "requirement_groups", "effective_date", "expiry_date",
              "network_product_codes", "min_value", "max_value", "value_basis", "currency",
              "min_weight", "max_weight", "other_logic"]


# --------------------------------------------------------------------------- #
# options (dropdowns) from the loaded workbook and package
# --------------------------------------------------------------------------- #

def load_options(session, country: str) -> dict[str, Any]:
    from sqlalchemy import select

    from tools.core.models import PermittedValue, Rule, SirgDef
    permitted: dict[str, set[str]] = {}
    for field, value in session.execute(select(PermittedValue.field, PermittedValue.value)).all():
        permitted.setdefault(field, set()).add(value)
    rows = session.execute(select(Rule.ctry_cd, Rule.region, Rule.network_product_codes)).all()
    regions = set(permitted.get("region", set())) | {r for _, r, _ in rows if r}
    codes: set[str] = set()
    for _, _, npc in rows:
        codes |= {c.strip().upper() for c in (npc or "").split(",") if c.strip()}
    country_regions = Counter(r for c, r, _ in rows if c == country and r)
    groups = sorted({cd for cd in session.execute(select(SirgDef.cd)).scalars() if cd})
    return {
        "region": sorted(regions),
        "region_default": country_regions.most_common(1)[0][0] if country_regions else None,
        "shipment_type": sorted(permitted.get("shipment_type") or {"B2B", "B2C", "B2B/B2C"}),
        "value_basis": sorted(permitted.get("value_basis") or {"DV", "IV"}),
        "currency": sorted(permitted.get("currency", set())),
        "currency_all": sorted(set(COMMON_CURRENCIES) | permitted.get("currency", set())),
        "network_product_codes": sorted(codes),
        "requirement_groups": groups,
        "min_ops": list(MIN_OPS), "max_ops": list(MAX_OPS),
        "country": country,
    }


def field_specs(options: dict[str, Any]) -> list[dict[str, Any]]:
    """The fields with their dropdown values and the 'accepted values' help."""
    out = []
    for f in FIELDS:
        spec = dict(f)
        key = f["key"]
        if key in ("region", "shipment_type", "value_basis", "network_product_codes", "requirement_groups"):
            spec["options"] = options.get(key, [])
        elif key == "currency":
            spec["options"] = options.get("currency_all", [])
            spec["workbook_options"] = options.get("currency", [])
        elif f["kind"] == "bound":
            spec["ops"] = options["min_ops"] if f["side"] == "min" else options["max_ops"]
        if key == "region" and options.get("region"):
            spec["accepted"] += f" Values: {', '.join(options['region'])}."
        if key == "currency" and options.get("currency"):
            spec["accepted"] += f" Already in the workbook: {', '.join(options['currency'])}."
        out.append(spec)
    return out


# --------------------------------------------------------------------------- #
# reading plain text
# --------------------------------------------------------------------------- #

_NONE_WORDS = re.compile(r"^\s*(none|no|nope|n/?a|not applicable|nothing|-|no condition|no other condition|"
                         r"no expiry|no end date|never|open[- ]ended|all|any|all products|no minimum|no maximum|"
                         r"no limit|no value limit|no weight limit)\s*[.!]?\s*$", re.I)
_DATE = r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})"
_NUM = r"(\d+(?:[.,]\d+)?)(?!\d)"


def parse_date(text: str) -> Optional[str]:
    m = re.search(_DATE, text or "")
    if not m:
        return None
    s = m.group(1)
    try:
        if re.match(r"\d{4}-", s):
            d = dt.date.fromisoformat("-".join(p.zfill(2) for p in s.split("-")))
        else:
            day, month, year = re.split(r"[-/.]", s)
            d = dt.date(int(year), int(month), int(day))
    except ValueError:
        return None
    return d.isoformat()


def _num(s: str) -> float:
    return float(s.replace(",", "."))


_OP_WORDS = [
    (r"(?:>=|≥|=>|at least|minimum(?: of)?|min\.?|from|not less than|starting at)", ">="),
    (r"(?:>|more than|greater than|over|above|exceeding|exceeds|higher than)", ">"),
    (r"(?:<=|≤|=<|up to|at most|maximum(?: of)?|max\.?|not more than|until|no more than)", "<="),
    (r"(?:<|less than|below|under|lower than)", "<"),
    (r"(?:=|==|equal to|exactly)", "="),
]


def parse_bound(text: str, side: str) -> Optional[dict[str, Any]]:
    """'> 150', '>=150', 'over 150', '150' (side default) → {'op', 'value'}."""
    t = (text or "").strip()
    for words, op in _OP_WORDS:
        m = re.search(rf"{words}\s*(?:€|\$|[A-Z]{{3}})?\s*{_NUM}", t, re.I)
        if m:
            if side == "min" and op in ("<", "<="):
                continue
            if side == "max" and op in (">", ">="):
                continue
            return {"op": op, "value": _num(m.group(1))}
    m = re.fullmatch(rf"(?:€|\$|[A-Z]{{3}})?\s*{_NUM}\s*(?:€|\$|[A-Z]{{3}}|kg)?", t, re.I)
    if m:
        return {"op": ">=" if side == "min" else "<=", "value": _num(m.group(1))}
    return None


def _bounds_in(text: str, unit: str) -> dict[str, dict[str, Any]]:
    """Value or weight limits stated anywhere in a sentence."""
    out: dict[str, dict[str, Any]] = {}
    kg = r"\s*(?:kg|kgs|kilo(?:gram)?s?)\b"
    cur = r"\s*(?:€|\$|eur|usd|bgn|[A-Z]{3})?"
    tail = kg if unit == "kg" else r"(?!\s*(?:kg|kgs|kilo))"
    between = re.search(rf"between{cur}\s*{_NUM}{('(?:' + kg + ')?') if unit == 'kg' else ''}\s*(?:and|-|to){cur}\s*{_NUM}{tail}",
                        text, re.I)
    if between:
        return {"min": {"op": ">=", "value": _num(between.group(1))},
                "max": {"op": "<=", "value": _num(between.group(2))}}
    for words, op in _OP_WORDS[:4]:
        for m in re.finditer(rf"{words}{cur}\s*{_NUM}{tail}", text, re.I):
            # Skip numbers that are part of a date or a weight when reading values.
            after = text[m.end():m.end() + 6]
            if unit == "value" and re.match(r"[-/.]\d", after):
                continue
            side = "min" if op in (">", ">=") else "max"
            out.setdefault(side, {"op": op, "value": _num(m.group(1))})
    return out


_COND_PATTERNS = [
    (re.compile(r"\bSDT\b[^.;,]*?\b(blank|empty|missing|absent|not present|no value)\b", re.I),
     lambda m: {"type": "short_code", "op": "is blank", "values": "SDT"}),
    (re.compile(r"\b(?:SDT)\b", re.I),
     lambda m: {"type": "short_code", "op": "is present (has a value)", "values": "SDT"}),
    (re.compile(r"\b(?:no|not|without|excluding|except)\s+(?:the\s+)?(?:service\s+code\s+)?(?:DD|DTP)\b", re.I),
     lambda m: {"type": "service_code", "op": "has none of", "values": "DD"}),
    (re.compile(r"\bservice\s+code\s+(?:is\s+)?not\s+DD\b", re.I),
     lambda m: {"type": "service_code", "op": "has none of", "values": "DD"}),
    (re.compile(r"\b(?:with|has|includes?)\s+(?:the\s+)?(?:service\s+code\s+)?(?:DD|DTP)\b|\bDTP\b", re.I),
     lambda m: {"type": "service_code", "op": "has any of", "values": "DD"}),
    (re.compile(r"\bincoterms?\s+(?:is\s+)?(DDP|DAP|EXW|DDU|CIF|FOB)\b|\b(DDP|DAP|EXW)\b"),
     lambda m: {"type": "incoterm", "op": "is one of", "values": m.group(1) or m.group(2)}),
    (re.compile(r"\b(?:origin|from|shipped from)\s+(?:country\s+)?([A-Z]{2})\b"),
     lambda m: {"type": "origin_country", "op": "is one of", "values": m.group(1)}),
]


def conditions_in(text: str) -> list[dict[str, Any]]:
    """Builder clauses for the conditions named in the text (first match per kind wins)."""
    clauses: list[dict[str, Any]] = []
    kinds: set[str] = set()
    for rx, make in _COND_PATTERNS:
        m = rx.search(text or "")
        if not m:
            continue
        clause = make(m)
        if clause["type"] in kinds:
            continue
        kinds.add(clause["type"])
        clauses.append(clause)
    return clauses


def logic_from_text(text: str) -> Optional[str]:
    clauses = conditions_in(text)
    if not clauses:
        return None
    from tools.ruleconfig import build_expression
    try:
        return build_expression(clauses, "and")["expression"]
    except ValueError:
        return None


def _groups_in(text: str, options: dict[str, Any]) -> list[str]:
    known = set(options.get("requirement_groups") or [])
    explicit = re.search(r"(?:requirement\s+groups?|documents?|groups?)\s*(?:is|are|:|=)\s*([A-Z0-9 ,/&]+)", text)
    found: list[str] = []
    for m in re.finditer(r"\b(?:provide|provides|request|requests|requested|need|needs|require|requires|required|"
                         r"raise|raises|submit|ask for|asks for)\s+(?:an?\s+|the\s+)?([A-Z][A-Z0-9]{1,7}"
                         r"(?:\s*(?:,|/|and|&)\s*[A-Z][A-Z0-9]{1,7})*)\b", text):
        found += [g.strip() for g in re.split(r",|/|&|\band\b", m.group(1)) if g.strip()]
    if explicit:
        found += [g.strip().upper() for g in re.split(r"[,/&]|\band\b", explicit.group(1)) if g.strip()]
    for token in re.findall(r"\b[A-Z][A-Z0-9]{1,7}\b", text):
        if token in known and token not in found:
            found.append(token)
    country = options.get("country")
    noise = {country, "B2B", "B2C", "DV", "IV", "EU", "ME", "SB", "AM", "AP", "DD", "DTP", "DDP", "DAP", "EXW",
             "SDT", "RTP", "UAT", "M2C", "NA", "KG"} | set(COMMON_CURRENCIES)
    return [g for g in found if g not in noise and re.fullmatch(r"[A-Z][A-Z0-9]{1,7}", g)]


def extract(text: str, options: dict[str, Any]) -> dict[str, Any]:
    """Read every M2C criterion the text states. Unstated ones are left out."""
    t = text or ""
    up = t.upper()
    out: dict[str, Any] = {"country": options.get("country")}

    regions = options.get("region") or []
    for r in regions:
        if re.search(rf"\b{re.escape(r)}\b", t):
            out["region"] = r
            break
    if "region" not in out:
        for word, code in (("europe", "EU"), ("middle east", "ME"), ("americas", "AM"), ("asia", "AP")):
            if word in t.lower() and (not regions or code in regions):
                out["region"] = code
                break

    if re.search(r"\bboth\b|B2B\s*(?:/|and|&|or)\s*B2C|B2C\s*(?:/|and|&|or)\s*B2B", t, re.I):
        out["shipment_type"] = "B2B/B2C"
    elif re.search(r"\bB2C\b|consumer|private (?:individual|person)s?", t, re.I):
        out["shipment_type"] = "B2C"
    elif re.search(r"\bB2B\b|business(?:es)? (?:shipments|customers|receivers)", t, re.I):
        out["shipment_type"] = "B2B"

    eff = re.search(rf"(?:effective|from|starting|start(?:s|ing)?|as of|go[- ]live)\D{{0,20}}?{_DATE}", t, re.I)
    if eff:
        out["effective_date"] = parse_date(eff.group(1))
    exp = re.search(rf"(?:expir\w*|until|till|valid to|end(?:s|ing)?(?: on)?|to)\D{{0,12}}?{_DATE}", t, re.I)
    if exp and (not eff or exp.start() != eff.start()):
        d = parse_date(exp.group(1))
        if d and d != out.get("effective_date"):
            out["expiry_date"] = d
    if re.search(r"no expiry|does not expire|doesn't expire|no end date|open[- ]ended|indefinite", t, re.I):
        out["expiry_date"] = NA
    if "effective_date" not in out:
        dates = re.findall(_DATE, t)
        if len(dates) == 1 and "expiry_date" not in out:
            out["effective_date"] = parse_date(dates[0])

    npc = re.search(r"(?:network\s+)?product\s+codes?\s*(?:is|are|:|=)?\s*([A-Z0-9](?:\s*(?:,|and)\s*[A-Z0-9])*)\b", t)
    if npc:
        out["network_product_codes"] = [c.strip().upper() for c in re.split(r",|and", npc.group(1)) if c.strip()]
    elif re.search(r"all (?:network )?products?|any product", t, re.I):
        out["network_product_codes"] = NA

    if re.search(r"declared value|\bDV\b", t, re.I):
        out["value_basis"] = "DV"
    elif re.search(r"intrinsic value|intristic value|\bIV\b", t, re.I):
        out["value_basis"] = "IV"

    if "€" in t:
        out["currency"] = "EUR"
    else:
        for code in options.get("currency_all") or COMMON_CURRENCIES:
            if re.search(rf"\b{code}\b", up):
                out["currency"] = code
                break
        if "currency" not in out and "$" in t:
            out["currency"] = "USD"

    values = _bounds_in(t, "value")
    weights = _bounds_in(t, "kg")
    if "min" in values:
        out["min_value"] = values["min"]
    if "max" in values:
        out["max_value"] = values["max"]
    if values and "min" not in values and re.search(r"\b(?:below|under|up to|less than|at most|<)", t, re.I):
        out["min_value"] = NA
    if values and "max" not in values and re.search(r"\b(?:above|over|more than|greater than|at least|>)", t, re.I):
        out["max_value"] = NA
    if "min" in weights:
        out["min_weight"] = weights["min"]
    if "max" in weights:
        out["max_weight"] = weights["max"]
    if re.search(r"any weight|no weight limit|regardless of weight", t, re.I):
        out.setdefault("min_weight", NA)
        out.setdefault("max_weight", NA)
    if re.search(r"any value|no value limit|regardless of value", t, re.I):
        out.setdefault("min_value", NA)
        out.setdefault("max_value", NA)

    logic = logic_from_text(t)
    if logic:
        out["other_logic"] = logic
    elif re.search(r"no other (?:condition|logic)|no further condition", t, re.I):
        out["other_logic"] = NA

    groups = _groups_in(t, options)
    if groups:
        out["requirement_groups"] = groups
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def answer_for(key: str, text: str, options: dict[str, Any]) -> Any:
    """Read the answer to the question asked about ``key``. ``None`` = not understood."""
    f = FIELD_BY_KEY[key]
    t = (text or "").strip()
    if _NONE_WORDS.match(t):
        return None if f["required"] else NA
    kind = f["kind"]
    if kind == "choice":
        opts = options.get(key) or []
        for o in sorted(opts, key=len, reverse=True):
            if re.search(rf"(?<![A-Z/]){re.escape(o)}(?![A-Z/])", t.upper()):
                return o
        got = extract(t, options).get(key)
        if got is None and not opts and re.fullmatch(r"[A-Za-z]{2,3}(?:/[A-Za-z]{2,3})?", t):
            got = t.upper()        # no list loaded to choose from: take the code as given
        return got
    if kind == "date":
        return parse_date(t)
    if kind == "multi":
        codes = [c.strip().upper() for c in re.split(r"[,;\s]+|\band\b", t) if c.strip()]
        codes = [c for c in codes if re.fullmatch(r"[A-Z0-9]{1,3}", c)]
        return codes or None
    if kind == "currency":
        m = re.search(r"\b([A-Za-z]{3})\b", t)
        return "EUR" if "€" in t else (m.group(1).upper() if m else None)
    if kind == "bound":
        return parse_bound(t, f["side"])
    if kind == "text":
        return logic_from_text(t) or t
    if kind == "groups":
        # A direct answer is a list of codes; otherwise read them from the sentence.
        direct = [g.strip().upper() for g in re.split(r"[,;/&]|\band\b", t)]
        if direct and all(re.fullmatch(r"[A-Z][A-Z0-9]{1,7}", g) for g in direct):
            return direct
        return _groups_in(t, options) or None
    return t


# --------------------------------------------------------------------------- #
# checking
# --------------------------------------------------------------------------- #

def _is_num_bound(v: Any) -> bool:
    return isinstance(v, dict) and isinstance(v.get("value"), (int, float))


def normalise(criteria: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    c = {k: v for k, v in (criteria or {}).items() if k in FIELD_BY_KEY and v not in (None, "", [])}
    c["country"] = options.get("country") or c.get("country")
    for key in ("region", "shipment_type", "value_basis", "currency"):
        if isinstance(c.get(key), str) and c[key] != NA:
            c[key] = c[key].strip().upper()
    if isinstance(c.get("network_product_codes"), str) and c["network_product_codes"] != NA:
        c["network_product_codes"] = [x.strip().upper() for x in c["network_product_codes"].split(",") if x.strip()]
    if isinstance(c.get("requirement_groups"), str):
        c["requirement_groups"] = [x.strip().upper() for x in c["requirement_groups"].split(",") if x.strip()]
    for key in ("effective_date", "expiry_date"):
        if isinstance(c.get(key), str) and c[key] != NA:
            c[key] = parse_date(c[key]) or c[key]
    for key in ("min_value", "max_value", "min_weight", "max_weight"):
        v = c.get(key)
        if isinstance(v, dict):
            try:
                c[key] = {"op": str(v.get("op") or (">=" if key.startswith("min") else "<=")).strip(),
                          "value": float(v["value"])}
            except (KeyError, TypeError, ValueError):
                c[key] = {"op": v.get("op"), "value": v.get("value"), "invalid": True}
        elif isinstance(v, (int, float)):
            c[key] = {"op": ">=" if key.startswith("min") else "<=", "value": float(v)}
        elif isinstance(v, str) and v != NA:
            c[key] = parse_bound(v, "min" if key.startswith("min") else "max") or {"op": None, "value": v, "invalid": True}
    if isinstance(c.get("other_logic"), str):
        c["other_logic"] = c["other_logic"].strip() or None
        if c["other_logic"] is None:
            c.pop("other_logic")
    # No value limit at all → value basis and currency do not apply.
    if c.get("min_value") == NA and c.get("max_value") == NA:
        c.setdefault("value_basis", NA)
        c.setdefault("currency", NA)
    return c


def check(criteria: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Errors, warnings and the questions still to ask."""
    c = normalise(criteria, options)
    errors: dict[str, str] = {}
    warnings: dict[str, str] = {}

    if c.get("region") not in (None, NA) and options.get("region") and c["region"] not in options["region"]:
        errors["region"] = f"'{c['region']}' is not a region in the workbook ({', '.join(options['region'])})."
    if c.get("shipment_type") not in (None, NA) and c["shipment_type"] not in ("B2B", "B2C", "B2B/B2C"):
        errors["shipment_type"] = "Must be B2B, B2C or B2B/B2C."
    for key in ("effective_date", "expiry_date"):
        v = c.get(key)
        if v not in (None, NA):
            try:
                dt.date.fromisoformat(v)
            except (TypeError, ValueError):
                errors[key] = "Not a valid date — use DD-MM-YYYY."
    if (c.get("effective_date") not in (None, NA) and c.get("expiry_date") not in (None, NA)
            and "expiry_date" not in errors and "effective_date" not in errors
            and c["expiry_date"] < c["effective_date"]):
        errors["expiry_date"] = "The expiry date is before the effective date."
    npc = c.get("network_product_codes")
    if isinstance(npc, list):
        bad = [x for x in npc if not re.fullmatch(r"[A-Z0-9]{1,3}", x)]
        if bad:
            errors["network_product_codes"] = f"Not a product code: {', '.join(bad)} (letters/digits, max 3)."
        unknown = [x for x in npc if x not in (options.get("network_product_codes") or []) and x not in bad]
        if unknown and options.get("network_product_codes"):
            warnings["network_product_codes"] = f"New code(s) not used in the workbook yet: {', '.join(unknown)}."
    for key in ("min_value", "max_value", "min_weight", "max_weight"):
        v = c.get(key)
        if v in (None, NA):
            continue
        side = FIELD_BY_KEY[key]["side"]
        ops = MIN_OPS if side == "min" else MAX_OPS
        if not _is_num_bound(v) or v.get("invalid"):
            errors[key] = "Give an operator and a number, e.g. " + ("> 150." if side == "min" else "<= 150.")
        elif v["op"] not in ops:
            errors[key] = f"The operator must be one of {', '.join(ops)}."
        elif v["value"] < 0:
            errors[key] = "Must be 0 or more."
    for lo, hi, what in (("min_value", "max_value", "value"), ("min_weight", "max_weight", "weight")):
        a, b = c.get(lo), c.get(hi)
        if _is_num_bound(a) and _is_num_bound(b) and lo not in errors and hi not in errors:
            a2, b2 = to_inclusive(lo, a), to_inclusive(hi, b)
            if a2 > b2:
                errors[hi] = f"The maximum {what} is below the minimum {what}."
    has_value_band = _is_num_bound(c.get("min_value")) or _is_num_bound(c.get("max_value"))
    if c.get("value_basis") not in (None, NA) and c["value_basis"] not in ("DV", "IV"):
        errors["value_basis"] = "Must be DV (declared value) or IV (intrinsic value)."
    cur = c.get("currency")
    if cur not in (None, NA):
        if not re.fullmatch(r"[A-Z]{3}", cur):
            errors["currency"] = "Use a three-letter ISO code, e.g. EUR."
        elif options.get("currency") and cur not in options["currency"]:
            warnings["currency"] = f"{cur} is not in the workbook's currency list yet — the CCRE team will add it."
    if has_value_band:
        for key in ("value_basis", "currency"):
            if c.get(key) == NA:
                errors[key] = "Needed because a value limit is given."
    logic = c.get("other_logic")
    if logic not in (None, NA):
        from tools.core import grammar
        if any(d.code == "EXPR_PARSE" for d in grammar.analyse(logic)):
            warnings["other_logic"] = "Written in plain words — the CCRE team will convert it into an expression."
    groups = c.get("requirement_groups")
    if isinstance(groups, list):
        known = set(options.get("requirement_groups") or [])
        unknown = [g for g in groups if known and g not in known]
        if unknown:
            warnings["requirement_groups"] = (f"{', '.join(unknown)} is not in the config package yet — "
                                              "Support will need to add it.")

    missing = []
    for key in _ASK_ORDER:
        f = FIELD_BY_KEY[key]
        # Value basis and currency are only asked once a value limit is given.
        if key in ("value_basis", "currency") and not has_value_band:
            continue
        if c.get(key) is None or (key == "requirement_groups" and not c.get(key)):
            question = f["question"]
            if key == "region" and options.get("region_default"):
                question += f" ({c.get('country')}'s existing M2C rows use {options['region_default']}.)"
            missing.append({"field": key, "label": f["label"], "question": question, "accepted": f["accepted"]})
    return {"criteria": c, "errors": errors, "warnings": warnings, "missing": missing,
            "complete": not missing and not errors, "m2c_row": to_m2c(c) if not errors else None}


# --------------------------------------------------------------------------- #
# into the M2C
# --------------------------------------------------------------------------- #

def to_inclusive(key: str, bound: dict[str, Any]) -> float:
    """The workbook's inclusive number for a bound: '> 150' → 150.01, '< 150' → 149.99."""
    v = float(bound["value"])
    if bound["op"] == ">":
        return round(v + STRICT_STEP, 4)
    if bound["op"] == "<":
        return round(v - STRICT_STEP, 4)
    return v


def to_m2c(c: dict[str, Any]) -> dict[str, Any]:
    """The M2C Import row values these criteria give (one row per requirement group)."""
    def bound(key: str) -> Optional[float]:
        v = c.get(key)
        return to_inclusive(key, v) if _is_num_bound(v) else None

    row = {
        "region": None if c.get("region") in (None, NA) else c["region"],
        "ctry_cd": c.get("country"),
        "shipment_type": None if c.get("shipment_type") in (None, NA) else c["shipment_type"],
        "effective_date": None if c.get("effective_date") in (None, NA) else c["effective_date"],
        "expiry_date": None if c.get("expiry_date") in (None, NA) else c["expiry_date"],
        "network_product_codes": ",".join(c["network_product_codes"])
        if isinstance(c.get("network_product_codes"), list) else None,
        "value_basis": None if c.get("value_basis") in (None, NA) else c["value_basis"],
        "currency": None if c.get("currency") in (None, NA) else c["currency"],
        "min_value": bound("min_value"), "max_value": bound("max_value"),
        "min_weight": bound("min_weight"), "max_weight": bound("max_weight"),
        "other_logic": None if c.get("other_logic") in (None, NA) else c["other_logic"],
    }
    # '= X' fixes both ends.
    for lo, hi in (("min_value", "max_value"), ("min_weight", "max_weight")):
        for key in (lo, hi):
            v = c.get(key)
            if _is_num_bound(v) and v["op"] == "=":
                row[lo] = row[hi] = float(v["value"])
    return row


def describe(c: dict[str, Any]) -> list[tuple[str, str]]:
    """(label, value) pairs for showing the criteria back to people."""
    def show(key: str) -> str:
        v = c.get(key)
        if v is None:
            return "— (missing)"
        if v == NA:
            return {"expiry_date": "No expiry", "network_product_codes": "All products",
                    "other_logic": "None"}.get(key, "Not applicable")
        if isinstance(v, list):
            return ", ".join(v)
        if isinstance(v, dict):
            unit = " kg" if "weight" in key else (f" {c['currency']}" if c.get("currency") not in (None, NA) else "")
            return f"{v.get('op')} {v.get('value')}{unit}"
        if key.endswith("_date"):
            try:
                return dt.date.fromisoformat(v).strftime("%d-%m-%Y")
            except ValueError:
                return v
        return str(v)
    return [(f["label"], show(f["key"])) for f in FIELDS]
