"""Web search collector using DuckDuckGo."""

import logging

from .base import BaseCollector, NewsItem

logger = logging.getLogger("web-search")


class WebSearchCollector(BaseCollector):
    """Search targeted tech sites using DuckDuckGo."""

    def __init__(self, queries: list[str], max_per_query: int = 5):
        super().__init__("web_search")
        self.queries = queries
        self.max_per_query = max_per_query

    def collect(self) -> list[NewsItem]:
        try:
            from ddgs import DDGS
        except ImportError:
            logger.warning("duckduckgo_search not installed, skipping web search")
            return []

        items: list[NewsItem] = []
        with DDGS() as ddgs:
            for query in self.queries:
                try:
                    results = list(
                        ddgs.text(
                            query,
                            region="cn-zh",
                            safesearch="off",
                            max_results=self.max_per_query,
                        )
                    )
                    for r in results:
                        title = (r.get("title") or "").strip()
                        if not title or len(title) < 8:
                            continue
                        body = (r.get("body") or "")[:500]
                        url = (r.get("href") or "").strip()
                        items.append(
                            NewsItem(
                                source="web_search",
                                title=title[:200],
                                body=body,
                                url=url,
                            )
                        )
                except Exception as e:
                    logger.warning(
                        "DDGS query failed '%s...': %s", query[:40], e
                    )
                    continue

        logger.info("Web search: collected %d items from %d queries", len(items), len(self.queries))
        return items
