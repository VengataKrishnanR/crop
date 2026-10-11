"""Grammar tests.

The cases below are the expressions actually found in the workbook, including the
two defects, so a regression here is a regression against real data.
"""
from __future__ import annotations

import pytest

from tools.core import grammar

LIVE_EXPRESSIONS = [
    '!serviceCodeList.contains("DD")',
    'serviceCodeList.contains("DD")',
    '!serviceCodeList.contains("DD")&&!serviceCodeList.contains("DS")',
    'incotermCodeList.contains("DDP")',
    'hscode("inboundHsCode","<blank>")',
    'matchCiMask("shortCode|==|SDT","value|==|<blank>")',
    'matchCiMask("shortCode|==|SDT","value|!=|<blank>")&& !serviceCodeList.contains("DD")',
    'OriginCountry!="UK" && !serviceCodeList.contains("DD")',
    'serviceCodeList.contains("DE") || serviceCodeList.contains("DS")',
]


@pytest.mark.parametrize("expression", LIVE_EXPRESSIONS)
def test_live_expressions_parse(expression: str) -> None:
    grammar.parse(expression)


@pytest.mark.parametrize("expression", LIVE_EXPRESSIONS)
def test_live_expressions_have_no_errors(expression: str) -> None:
    errors = [d for d in grammar.analyse(expression) if d.severity == "error"]
    assert errors == [], f"{expression} produced {errors}"


def test_normalise_is_whitespace_insensitive() -> None:
    a = 'matchCiMask("shortCode|==|SDT","value|!=|<blank>")&& !serviceCodeList.contains("DD")'
    b = 'matchCiMask("shortCode|==|SDT", "value|!=|<blank>") && !serviceCodeList.contains("DD")'
    assert grammar.normalise(a) == grammar.normalise(b)


def test_the_bg_correction_is_not_equal_to_the_stale_expression() -> None:
    """The defect the BG thread was about must be a detectable difference."""
    stale = '!serviceCodeList.contains("DD")'
    corrected = 'matchCiMask("shortCode|==|SDT","value|!=|<blank>")&& !serviceCodeList.contains("DD")'
    assert grammar.normalise(stale) != grammar.normalise(corrected)


def test_blank_presence_polarity_is_significant() -> None:
    """``==|<blank>`` and ``!=|<blank>`` must never normalise together."""
    absent = 'matchCiMask("shortCode|==|SDT","value|==|<blank>")'
    present = 'matchCiMask("shortCode|==|SDT","value|!=|<blank>")'
    assert grammar.normalise(absent) != grammar.normalise(present)


def test_palette_comma_syntax_is_an_error() -> None:
    """The Other Logic palette's comma form would silently misbehave if copied."""
    diagnostics = grammar.analyse('(matchCiMask("shortCode,==,SDT") && matchCiMask("value,==,<blank>") )')
    codes = {d.code for d in diagnostics}
    assert "EXPR_MASK_SYNTAX" in codes
    assert any(d.severity == "error" for d in diagnostics)
    # The fix is suggested, not just the complaint.
    assert any("shortCode|==|SDT" in d.message for d in diagnostics)


def test_precedence_trap_is_reported() -> None:
    """`a || b && c` applies the && to its neighbour only -- a real workbook bug."""
    expression = (
        'OriginCountry=="TR"||OriginCountry=="SD"||OriginCountry=="TW" '
        '&& destinationServiceArea.contains("AUH")'
    )
    codes = {d.code for d in grammar.analyse(expression)}
    assert "EXPR_PRECEDENCE" in codes


def test_bracketing_silences_the_precedence_warning() -> None:
    expression = (
        '(OriginCountry=="TR"||OriginCountry=="SD") '
        '&& destinationServiceArea.contains("AUH")'
    )
    codes = {d.code for d in grammar.analyse(expression)}
    assert "EXPR_PRECEDENCE" not in codes


def test_repeated_term_is_reported() -> None:
    expression = 'OriginCountry=="IN"||OriginCountry=="CN"||OriginCountry=="IN"'
    codes = {d.code for d in grammar.analyse(expression)}
    assert "EXPR_REPEATED_TERM" in codes


def test_unknown_function_is_an_error() -> None:
    diagnostics = grammar.analyse('matchMask("a|==|b")')
    assert any(d.code == "EXPR_UNKNOWN_FN" and d.severity == "error" for d in diagnostics)


def test_unknown_list_is_an_error() -> None:
    diagnostics = grammar.analyse('serviceCodes.contains("DD")')
    assert any(d.code == "EXPR_UNKNOWN_FIELD" and d.severity == "error" for d in diagnostics)


def test_unknown_method_is_an_error() -> None:
    diagnostics = grammar.analyse('serviceCodeList.includes("DD")')
    assert any(d.code == "EXPR_UNKNOWN_METHOD" for d in diagnostics)


def test_hscode_arity_is_enforced() -> None:
    diagnostics = grammar.analyse('hscode("inboundHsCode")')
    assert any(d.code == "EXPR_ARITY" for d in diagnostics)


@pytest.mark.parametrize("bad", ['serviceCodeList.contains("DD"', 'OriginCountry ==', '&& foo', '"x" "y"'])
def test_malformed_expressions_are_reported_not_raised(bad: str) -> None:
    diagnostics = grammar.analyse(bad)
    assert any(d.code == "EXPR_PARSE" for d in diagnostics)


def test_empty_expression_is_clean() -> None:
    assert grammar.analyse("") == []
    assert grammar.analyse("   ") == []


def test_service_codes_are_extractable_for_test_generation() -> None:
    expression = '!serviceCodeList.contains("DD")&&!serviceCodeList.contains("DS")'
    assert grammar.referenced_service_codes(expression) == {"DD", "DS"}


def test_parse_raises_on_empty() -> None:
    with pytest.raises(grammar.ExpressionError):
        grammar.parse("")
