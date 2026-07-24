"""Podcast show notes collector using DuckDuckGo text search."""

import logging

from .base import BaseCollector, NewsItem

logger = logging.getLogger("podcast")


class PodcastCollector(BaseCollector):
    """Search for latest podcast episode show notes."""

    def __init__(self, sources: list[str], max_per_source: int = 3):
        super().__init__("podcast")
        self.sources = sources
        self.max_per_source = max_per_source

    def collect(self) -> list[NewsItem]:
        try:
            from ddgs import DDGS
        except ImportError:
            logger.warning("duckduckgo_search not installed, skipping podcast search")
            return []

        items: list[NewsItem] = []
        with DDGS() as ddgs:
            for podcast in self.sources:
                query = f"{podcast} show notes 2026 最新"
                try:
                    results = list(
                        ddgs.text(
                            query,
                            region="cn-zh",
                            safesearch="off",
                            max_results=self.max_per_source,
                        )
                    )
                    for r in results:
                        title = (r.get("title") or "").strip()
                        if not title:
                            continue
                        body = (r.get("body") or "")[:500]
                        url = (r.get("href") or "").strip()
                        items.append(
                            NewsItem(
                                source=podcast,
                                title=title[:200],
                                body=body,
                                url=url,
                            )
                        )
                except Exception as e:
                    logger.warning(
                        "Podcast search failed for '%s': %s", podcast, e
                    )
                    continue

        logger.info(
            "Podcast: collected %d items from %d sources",
            len(items),
            len(self.sources),
        )
        return items
