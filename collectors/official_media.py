"""官方媒体/政府机构列表页采集器。

抓取各栏目列表页的标题+链接，做政府网站的一手信息源。政府站多为 GBK 编码，
需按页面 meta charset 声明解码后解析。
"""

import logging
import re
from urllib.parse import urljoin, urlparse

import requests
from lxml import html

from .base import BaseCollector, NewsItem

logger = logging.getLogger("official-media")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 15

_SKIP_TEXT = {
    "更多", "首页", "返回", "加载更多", "上一页", "下一页", "尾页",
    "联系我们", "网站地图", "关于我们", "友情链接", "设为首页", "加入收藏",
}


class OfficialMediaCollector(BaseCollector):
    """抓取政府机构栏目列表页，返回标题+链接+摘要。

    config: {"name": "网信办", "columns": [{"name": "政策法规", "url": "...", "max_items": 10}]}
    """

    def __init__(self, name: str, columns: list[dict]):
        super().__init__(name)
        self.columns = columns

    def collect(self) -> list[NewsItem]:
        items: list[NewsItem] = []
        for col in self.columns:
            items.extend(self._collect_column(col))
        return items

    def _collect_column(self, col: dict) -> list[NewsItem]:
        col_name = col.get("name", "")
        url = col.get("url", "")
        max_items = col.get("max_items", 10)
        if not url:
            return []

        try:
            resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("[%s/%s] 抓取失败: %s", self.name, col_name, e)
            return []

        doc = self._parse(resp.content)
        if doc is None:
            logger.warning("[%s/%s] 解析失败", self.name, col_name)
            return []

        seen: set[str] = set()
        out: list[NewsItem] = []
        page_domain = urlparse(url).netloc
        for a in doc.xpath("//a[@href]"):
            if len(out) >= max_items:
                break
            href = (a.get("href") or "").strip()
            title = (a.text_content() or "").strip()
            title = re.sub(r"\s+", " ", title)
            if not title or len(title) < 5:
                continue
            bare = title.rstrip(">»› >> ·")
            if bare in _SKIP_TEXT or title in _SKIP_TEXT:
                continue
            if href.lower().startswith(("javascript", "#", "mailto")):
                continue
            abs_url = urljoin(url, href)
            if abs_url in seen or not abs_url.startswith("http"):
                continue
            # 正文详情页过滤：排除外站导航和目录页（目录页以 / 结尾）
            if urlparse(abs_url).netloc != page_domain:
                continue
            if abs_url.endswith("/"):
                continue
            seen.add(abs_url)

            # snippet：取父节点（li/p/td）文本前 100 字
            snippet = ""
            parent = a.getparent()
            if parent is not None:
                snippet = re.sub(r"\s+", " ", parent.text_content()).strip()[:100]

            out.append(
                NewsItem(
                    source=f"官方/{self.name}/{col_name}",
                    title=title[:200],
                    body=snippet,
                    url=abs_url,
                )
            )

        logger.info("[%s/%s]: %d items", self.name, col_name, len(out))
        return out

    @staticmethod
    def _parse(content: bytes):
        """按 meta charset 声明解码，缺失时依次尝试 utf-8 / gbk。"""
        text = None
        m = re.search(rb'charset=["\']?([a-zA-Z0-9-]+)', content[:4096])
        if m:
            charset = m.group(1).decode("ascii", "ignore").lower()
            try:
                text = content.decode(charset)
            except (UnicodeDecodeError, LookupError):
                text = None
        for enc in ("utf-8", "gbk"):
            if text is not None:
                break
            try:
                text = content.decode(enc)
            except UnicodeDecodeError:
                continue
        if text is None:
            text = content.decode("utf-8", "ignore")
        try:
            return html.fromstring(text)
        except Exception:
            return None
