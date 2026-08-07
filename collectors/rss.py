"""RSS feed collector using lxml."""

import logging
import re
import time

import requests
from lxml import etree

from .base import BaseCollector, NewsItem

logger = logging.getLogger("rss-collector")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 15

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class RSSCollector(BaseCollector):
    """Collect news from an RSS feed URL."""

    def __init__(self, name: str, feed_url: str, max_items: int = 20):
        super().__init__(name)
        self.feed_url = feed_url
        self.max_items = max_items

    def collect(self) -> list[NewsItem]:
        resp = requests.get(
            self.feed_url,
            timeout=TIMEOUT,
            headers={"User-Agent": UA},
        )
        resp.raise_for_status()

        parser = etree.XMLParser(
            recover=True,
            resolve_entities=False,
            no_network=True,
            remove_comments=True,
        )
        root = etree.fromstring(resp.content, parser=parser)

        items: list[NewsItem] = []
        # RSS uses item; Atom uses entry. Support both so Atom feeds are not silently empty.
        entries = root.xpath("//item") or root.xpath("//*[local-name()='entry']")
        for entry in entries[: self.max_items]:
            title_nodes = entry.xpath("title/text()")
            if not title_nodes:
                continue
            title = title_nodes[0].strip()
            if not title or len(title) < 5:
                continue

            # Link: handle CDATA and raw <link>
            raw_link = entry.xpath("string(link)").strip()
            if not raw_link:
                hrefs = entry.xpath("*[local-name()='link']/@href")
                raw_link = (hrefs[0] if hrefs else "").strip()

            # Description: strip HTML tags
            desc = ""
            for xpath in ["description/text()", "description"]:
                nodes = entry.xpath(xpath)
                if nodes:
                    raw = str(nodes[0])
                    desc = re.sub(r"<[^>]+>", "", raw).strip()[:500]
                    break

            # Fallback to content:encoded
            if not desc:
                content_nodes = entry.xpath(
                    "content:encoded/text()", namespaces=NS
                )
                if content_nodes:
                    desc = re.sub(
                        r"<[^>]+>", "", content_nodes[0]
                    ).strip()[:500]

            pub_date = (entry.xpath("pubDate/text()") or [""])[0].strip()
            if not pub_date:
                pub_date = (entry.xpath("*[local-name()='published']/text()") or [""])[0].strip()
            if not pub_date:
                pub_date = (entry.xpath("*[local-name()='updated']/text()") or [""])[0].strip()

            items.append(
                NewsItem(
                    source=self.name,
                    title=title[:200],
                    body=desc,
                    url=raw_link if raw_link.startswith("http") else "",
                    publish_time=pub_date,
                )
            )

        logger.info(
            "RSS[%s]: collected %d items from %s",
            self.name,
            len(items),
            self.feed_url,
        )
        return items
