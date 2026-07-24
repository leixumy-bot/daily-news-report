"""Xiaohongshu collector using local MCP server."""

import json
import logging
from typing import Any

from .base import BaseCollector, NewsItem
from .mcp_client import XiaohongshuMCP

logger = logging.getLogger("xhs-collector")

# Accounts to follow on Xiaohongshu
TARGET_ACCOUNTS = ["CrazyAllen", "好运D", "AI前线", "AI产品"]

# Keywords to search for AI/Cloud content on Xiaohongshu
# Keep minimal - each search opens a headless browser and takes time
SEARCH_KEYWORDS = [
    "AI 大模型 云",
    "AI 创业 趋势",
]


class XiaohongshuCollector(BaseCollector):
    """Collect news and insights from Xiaohongshu."""

    def __init__(self, server_url: str = "http://localhost:18060"):
        super().__init__("小红书")
        self.xhs = XiaohongshuMCP(server_url)

    def collect(self) -> list[NewsItem]:
        items: list[NewsItem] = []

        # Check login first
        logged_in, status = self.xhs.check_login()
        if not logged_in:
            logger.warning(
                "Xiaohongshu not logged in. Please run the login tool.\n%s",
                status,
            )
            return items

        logger.info("Xiaohongshu logged in: %s", status[:60])

        # Search for each keyword
        for keyword in SEARCH_KEYWORDS:
            try:
                feeds = self.xhs.search_feeds(keyword)
                for feed in feeds[:3]:  # Top 3 per keyword
                    item = self._feed_to_item(feed, keyword)
                    if item:
                        items.append(item)
            except Exception as e:
                logger.warning(
                    "XHS search '%s' failed: %s", keyword[:20], e
                )
                continue

        # Deduplicate by feed ID
        seen = set()
        unique_items = []
        for item in items:
            key = item.url  # Use URL as dedup key
            if key and key not in seen:
                seen.add(key)
                unique_items.append(item)

        logger.info(
            "Xiaohongshu: collected %d items (from %d raw)",
            len(unique_items),
            len(items),
        )
        return unique_items

    def _feed_to_item(
        self, feed: dict, keyword: str
    ) -> NewsItem | None:
        """Convert a feed dict to a NewsItem."""
        try:
            note_card = feed.get("noteCard", {})
            title = note_card.get("displayTitle", "")
            if not title:
                return None

            user = note_card.get("user", {})
            nickname = user.get("nickname", user.get("nickName", ""))

            # Build URL from feed_id
            feed_id = feed.get("id", "")
            xsec_token = feed.get("xsecToken", "")
            url = ""
            if feed_id and xsec_token:
                url = (
                    f"https://www.xiaohongshu.com/explore/"
                    f"{feed_id}?xsec_token={xsec_token}"
                )

            return NewsItem(
                source=f"小红书/{nickname}" if nickname else "小红书",
                title=title[:200],
                body=f"关键词: {keyword} | 作者: {nickname}",
                url=url,
            )
        except Exception as e:
            logger.debug("XHS feed parse error: %s", e)
            return None
