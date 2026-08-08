import pytest

from daily_report import resolve_year_queries, validate_report_date


def test_resolve_year_queries_uses_report_year():
    queries = ["site:example.com AI 2026", "AI cloud"]
    assert resolve_year_queries(queries, "2027-01-01") == [
        "site:example.com AI 2027", "AI cloud"
    ]


def test_validate_report_date():
    assert validate_report_date("2026-08-08") == "2026-08-08"
    with pytest.raises(ValueError):
        validate_report_date("2026-8-8")
    with pytest.raises(ValueError):
        validate_report_date("2026-02-30")
