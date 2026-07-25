"""Feishu REST API client — direct calls without lark-cli.

Uses bot identity (app_id + app_secret) for all operations.
GitHub Actions compatible — no local CLI needed.
"""

import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger("feishu-api")

FEISHU_BASE = "https://open.feishu.cn/open-apis"

# Post content limit check
MAX_POST_BYTES = 38000


class FeishuAPI:
    """Direct Feishu Open API client using bot identity."""

    def __init__(self, app_id: str | None = None, app_secret: str | None = None):
        self.app_id = app_id or os.environ.get("LARK_APP_ID", "")
        self.app_secret = app_secret or os.environ.get("LARK_APP_SECRET", "")
        self._token: str = ""
        self._token_expires_at: float = 0
        if not self.app_id or not self.app_secret:
            raise ValueError("Feishu API requires LARK_APP_ID and LARK_APP_SECRET")

    def _ensure_token(self) -> str:
        if time.time() < self._token_expires_at - 60:
            return self._token
        resp = requests.post(
            f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data.get("tenant_access_token", "")
        self._token_expires_at = time.time() + data.get("expire", 7200)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
        }

    def send_group_message(self, chat_id: str, markdown_content: str) -> bool:
        """Send post (rich text) message with links and formatting."""
        if len(markdown_content.encode("utf-8")) > MAX_POST_BYTES:
            parts = self._split_content(markdown_content)
            for i, part in enumerate(parts):
                post = self._md_to_post(part)
                ok = self._post_message(chat_id, post)
                if not ok:
                    return False
            return True
        else:
            post = self._md_to_post(markdown_content)
            return self._post_message(chat_id, post)

    def _split_content(self, markdown: str) -> list[str]:
        """Split into curated + appendix when too long."""
        idx = markdown.find("## 📋 附录")
        if idx > 0:
            return [markdown[:idx].rstrip() + "\n\n📄 *完整附录见下一条消息*", markdown[idx:]]
        return [markdown]

    def _post_message(self, chat_id: str, post: dict) -> bool:
        payload = {
            "receive_id": chat_id,
            "msg_type": "post",
            "content": json.dumps({"zh_cn": post}, ensure_ascii=False),
        }
        resp = requests.post(
            f"{FEISHU_BASE}/im/v1/messages?receive_id_type=chat_id",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error("Feishu send failed: HTTP %d %s", resp.status_code, resp.text[:300])
            return False
        data = resp.json()
        if data.get("code") != 0:
            logger.error("Feishu send error: %s", data.get("msg", ""))
            return False
        return True

    def _md_to_post(self, markdown: str) -> dict:
        """Convert markdown → Feishu post rich text format.

        Post content is a list of paragraphs.
        Each paragraph is a list of inline elements.
        """
        # Extract @mention user_id
        user_open_id = ""
        m = re.search(r'<at user_id="([^"]+)"', markdown)
        if m:
            user_open_id = m.group(1)
            # Remove the at line
            markdown = re.sub(r'<at[^>]*>.*?</at>', "", markdown).strip()

        # Extract title
        title = "AI+Cloud 每日早报"
        m = re.search(r"# (.+)", markdown)
        if m:
            title = m.group(1).strip()

        # Split into paragraphs by double newline, but preserve single newlines within
        paragraphs = self._split_paragraphs(markdown)

        # Build post content
        content = []
        if user_open_id:
            content.append([
                {"tag": "at", "user_id": user_open_id},
                {"tag": "text", "text": "  早安！今日早报来了 👇"},
            ])

        for para in paragraphs:
            parsed = self._parse_para(para)
            if parsed:
                content.append(parsed)

        return {"title": title, "content": content}

    def _split_paragraphs(self, text: str) -> list[str]:
        """Split markdown into paragraphs, handling --- as separators."""
        # Split by blank lines (double newlines)
        blocks = re.split(r"\n\s*\n", text.strip())
        result = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            # Skip the # title line (already extracted as post title)
            if block.startswith("# ") and not block.startswith("## "):
                continue
            # ---- separator line
            if re.match(r"^-{3,}\s*$", block):
                result.append("---")
            else:
                result.append(block)
        return result

    def _parse_para(self, text: str) -> list[dict] | None:
        """Parse a single paragraph into inline elements list."""
        if not text.strip():
            return None

        # Horizontal rule
        if text.strip() == "---":
            return [{"tag": "hr"}]

        # Process inline elements in order
        # Tokenize: split into segments by **bold** or [link](url)
        tokens = self._tokenize(text)
        elements = []

        for token_type, token_text in tokens:
            if token_type == "bold":
                # Handle **bold text**
                elements.append({"tag": "text", "text": token_text, "style": ["bold"]})
            elif token_type == "link":
                # Handle [text](url)
                elements.append({"tag": "a", "text": token_text[0], "href": token_text[1]})
            elif token_type == "heading":
                # ## heading — render as bold text
                elements.append({"tag": "text", "text": token_text, "style": ["bold"]})
            elif token_type == "bullet":
                # Bullet item — prepend bullet prefix
                if elements:
                    elements.append({"tag": "text", "text": "\n"})
                elements.append({"tag": "text", "text": f"•  {token_text}"})
            elif token_type == "quote":
                # Blockquote
                if elements:
                    elements.append({"tag": "text", "text": "\n"})
                elements.append({"tag": "text", "text": token_text})
            elif token_type == "bold_link":
                # ***[bold link text](url)*** or **[text](url)**
                inner_text = token_text[0]
                inner_url = token_text[1]
                elements.append({"tag": "a", "text": inner_text, "href": inner_url})
            elif token_type == "text":
                elements.append({"tag": "text", "text": token_text})

        return elements if elements else None

    def _tokenize(self, text: str) -> list[tuple]:
        """Tokenize a paragraph into (type, content) tuples.

        Handles:
        - ## heading → ("heading", "text")
        - **bold** → ("bold", "text")
        - [link](url) → ("link", ("text", "url"))
        - > quote → ("quote", "text")
        - - bullet → ("bullet", "text")
        - plain text → ("text", "text")
        """
        text = text.strip()
        if not text:
            return []

        # Check if starts with ## (heading)
        if text.startswith("## "):
            return [("heading", text[3:].strip())]

        # Check if starts with > (blockquote)
        if text.startswith(">"):
            return [("quote", text[1:].strip())]

        # Check if starts with - or * (bullet)
        if text.startswith("- ") or text.startswith("* "):
            inner = text[2:].strip()
            if not inner:
                return []
            # Parse inline formatting inside bullet
            inline_tokens = self._tokenize_inline(inner)
            # Wrap in bullet type
            return [("bullet", t[1]) if t[0] == "text" else t for t in inline_tokens]

        # Regular paragraph — parse inline formatting
        return self._tokenize_inline(text)

    def _tokenize_inline(self, text: str) -> list[tuple]:
        """Parse inline bold and link formatting from text.

        Returns list of (type, content) tuples.
        """
        # Tokenize by splitting on:
        # **text** (bold), [text](url) (link)
        pattern = r"(\*\*\*?\[.*?\]\(.*?\)\*\*\*?|\*\*.*?\*\*|\[.*?\]\(.*?\))"
        parts = re.split(pattern, text)
        tokens = []

        for part in parts:
            if not part:
                continue

            # ***[link text](url)*** — bold link (rare, but handle)
            m = re.match(r"\*\*\*?\[(.*?)\]\((.*?)\)\*\*\*?", part)
            if m:
                tokens.append(("bold_link", (m.group(1), m.group(2))))
                continue

            # **bold text**
            m = re.match(r"\*\*(.*?)\*\*", part)
            if m:
                tokens.append(("bold", m.group(1)))
                continue

            # [link text](url)
            m = re.match(r"\[(.*?)\]\((.*?)\)", part)
            if m:
                tokens.append(("link", (m.group(1), m.group(2))))
                continue

            # Plain text — but preserve any remaining formatting indicators
            tokens.append(("text", part))

        return tokens
