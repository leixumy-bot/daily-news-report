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

# Feishu post message content limit: ~38000 bytes per message
# If exceeded, split into multiple messages
MAX_POST_SIZE = 35000


class FeishuAPI:
    """Direct Feishu Open API client using bot identity."""

    def __init__(self, app_id: str | None = None, app_secret: str | None = None):
        self.app_id = app_id or os.environ.get("LARK_APP_ID", "")
        self.app_secret = app_secret or os.environ.get("LARK_APP_SECRET", "")
        self._token: str = ""
        self._token_expires_at: float = 0

        if not self.app_id or not self.app_secret:
            raise ValueError(
                "Feishu API requires LARK_APP_ID and LARK_APP_SECRET "
                "(env vars or constructor args)"
            )

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
        expire = data.get("expire", 7200)
        self._token_expires_at = time.time() + expire
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
        }

    def send_group_message(self, chat_id: str, markdown_content: str) -> bool:
        """Send post (rich text) message. Supports links and long content."""
        # Check size and split if needed
        if len(markdown_content.encode("utf-8")) > MAX_POST_SIZE:
            # Send curated part as first message, appendix as second
            parts = self._split_content(markdown_content)
            for i, part in enumerate(parts):
                post = self._build_post(part, is_first=(i == 0))
                ok = self._send_post(chat_id, post)
                if not ok:
                    return False
            return True
        else:
            post = self._build_post(markdown_content)
            return self._send_post(chat_id, post)

    def _split_content(self, markdown: str) -> list[str]:
        """Split long content into curated + appendix parts."""
        # Find the appendix section
        appendix_marker = "## 📋 附录"
        header_end = "## 📖 精读版"

        curated_end = markdown.find(appendix_marker)
        if curated_end > 0:
            curated_part = markdown[:curated_end].rstrip()
            curated_part += "\n\n---\n📄 *完整附录因篇幅限制分段发送*"
            appendix_part = markdown[curated_end:]
            return [curated_part, appendix_part]
        return [markdown]

    def _send_post(self, chat_id: str, post: dict) -> bool:
        """Send a post message to the group."""
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
            logger.error(
                "Feishu send failed: HTTP %d %s",
                resp.status_code,
                resp.text[:300],
            )
            return False

        data = resp.json()
        if data.get("code") != 0:
            logger.error("Feishu send error: %s", data.get("msg", ""))
            return False

        return True

    def _build_post(self, markdown: str, is_first: bool = True) -> dict:
        """Convert markdown to Feishu post (rich text) format.

        Post format structure:
        {
            "title": "str",
            "content": [
                [{"tag": "text", "text": "..."}, {"tag": "a", "text": "...", "href": "..."}],
                [{"tag": "text", "text": "..."}]
            ]
        }
        """
        lines = markdown.strip().split("\n")

        # Process @mention
        user_open_id = ""
        cleaned_lines = []
        for line in lines:
            m = re.search(r'<at user_id="([^"]+)"', line)
            if m:
                user_open_id = m.group(1)
                continue
            cleaned_lines.append(line)

        # Extract title
        title = "AI+Cloud 每日早报"
        for line in cleaned_lines:
            if line.startswith("# ") and len(line) > 3:
                title = line[2:].strip()
                break

        paragraphs = []
        current_para = []

        for line in cleaned_lines:
            if line.strip() == "":
                if current_para:
                    paragraphs.append(self._parse_line("\n".join(current_para)))
                    current_para = []
                continue

            if line.strip() == "---":
                if current_para:
                    paragraphs.append(self._parse_line("\n".join(current_para)))
                    current_para = []
                paragraphs.append([{"tag": "hr"}])
                continue

            if line.startswith("## "):
                if current_para:
                    paragraphs.append(self._parse_line("\n".join(current_para)))
                    current_para = []
                paragraphs.append(self._parse_line(line, is_heading=True))
                continue

            current_para.append(line)

        if current_para:
            paragraphs.append(self._parse_line("\n".join(current_para)))

        # Prepend @mention
        if is_first and user_open_id:
            paragraphs.insert(
                0,
                [
                    {"tag": "at", "user_id": user_open_id},
                    {"tag": "text", "text": " 早安！今日早报来了 👇"},
                ],
            )

        return {"title": title, "content": paragraphs}

    def _parse_line(self, text: str, is_heading: bool = False) -> list[dict]:
        """Parse a text line into post format elements.

        Handles:
        - **bold** text
        - [link text](url) links
        - plain text
        - ## headings as bold
        """
        elements = []

        if is_heading:
            # Headings: bold + larger
            clean = text.lstrip("#").strip()
            elements.append({"tag": "text", "text": clean})
            return elements

        # Process **bold** and [text](url) patterns
        # Pattern: **[bold text]** or **bold text**
        parts = re.split(r"(\*\*.*?\*\*|\[.*?\]\(.*?\))", text)

        for part in parts:
            if not part:
                continue

            # Bold: **text**
            bold_match = re.match(r"\*\*(.*?)\*\*", part)
            if bold_match:
                elements.append({"tag": "text", "text": bold_match.group(1), "style": ["bold"]})
                continue

            # Link: [text](url)
            link_match = re.match(r"\[(.*?)\]\((.*?)\)", part)
            if link_match:
                elements.append({"tag": "a", "text": link_match.group(1), "href": link_match.group(2)})
                continue

            # Check if starts with > (blockquote)
            if part.strip().startswith(">"):
                elements.append({"tag": "text", "text": part.strip().lstrip(">").strip()})
                continue

            # Plain text
            elements.append({"tag": "text", "text": part})

        # Remove trailing empty text
        elements = [e for e in elements if e.get("text", "").strip() or e.get("tag") == "a"]

        return elements if elements else [{"tag": "text", "text": text}]
