from daily_report import resolve_year_queries


def test_resolve_year_queries_uses_report_year():
    queries = ["site:example.com AI 2026", "AI cloud"]
    assert resolve_year_queries(queries, "2027-01-01") == [
        "site:example.com AI 2027", "AI cloud"
    ]
