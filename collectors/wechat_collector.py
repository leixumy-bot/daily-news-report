"""WeChat public account article collector.

Uses Playwright to:
1. Log into mp.weixin.qq.com (user scans QR code once)
2. Fetch recent articles from followed AI/Cloud accounts
3. Extract article content

For Phase 1: also uses DDGS search to find WeChat articles.
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from .base import BaseCollector, NewsItem

logger = logging.getLogger("wechat-collector")

# Target WeChat public accounts (biz IDs)
TARGET_ACCOUNTS = [
    "科技之心",
    "Founder Park",
    "AI科技评论",
    "42章经",
    "硅谷101",
    "乱翻书",
]

WECHAT_SEARCH_URL = "https://mp.weixin.qq.com/mp/waathsearch"

COOKIES_FILE = Path(__file__).parent.parent / ".wechat_cookies.json"


class WechatCollector(BaseCollector):
    """Collect articles from WeChat public accounts."""

    def __init__(self):
        super().__init__("微信公众号")

    def collect(self) -> list[NewsItem]:
        items: list[NewsItem] = []

        # Method 1: Use DDGS to find WeChat articles (works without login)
        try:
            from ddgs import DDGS

            with DDGS() as ddgs:
                for account in TARGET_ACCOUNTS:
                    try:
                        query = f"site:mp.weixin.qq.com {account} AI"
                        results = list(
                            ddgs.text(
                                query,
                                region="cn-zh",
                                safesearch="off",
                                max_results=3,
                            )
                        )
                        for r in results:
                            title = (r.get("title") or "").strip()
                            if not title or len(title) < 10:
                                continue
                            body = (r.get("body") or "")[:500]
                            url = (r.get("href") or "").strip()
                            if not url or "mp.weixin.qq.com" not in url:
                                continue
                            items.append(
                                NewsItem(
                                    source=f"微信/{account}",
                                    title=title[:200],
                                    body=body,
                                    url=url,
                                )
                            )
                    except Exception as e:
                        logger.debug("WeChat search '%s' error: %s", account, e)
                        continue
        except ImportError:
            logger.warning("ddgs not installed, skipping WeChat search")

        # Deduplicate by URL
        seen = set()
        unique = []
        for item in items:
            if item.url and item.url not in seen:
                seen.add(item.url)
                unique.append(item)

        logger.info(
            "WeChat: collected %d unique items from %d accounts",
            len(unique),
            len(TARGET_ACCOUNTS),
        )
        return unique
