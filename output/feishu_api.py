"""Feishu REST API client — direct calls without lark-cli.

Uses bot identity (app_id + app_secret) for all operations.
GitHub Actions compatible — no local CLI needed.
"""

import json
import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger("feishu-api")

FEISHU_BASE = "https://open.feishu.cn/open-apis"


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
        """Get a valid tenant_access_token (cached with refresh)."""
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
        logger.debug("Feishu token refreshed (expires in %ds)", expire)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
        }

    def send_group_message(self, chat_id: str, markdown_content: str) -> bool:
        """Send an interactive card message to a group chat.

        The markdown_content is rendered as a card with a single markdown element.
        Returns True on success.
        """
        # Build card from markdown content
        card = self._build_card(markdown_content)
        payload = {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }

        resp = requests.post(
            f"{FEISHU_BASE}/im/v1/messages?receive_id_type=chat_id",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )

        if resp.status_code != 200:
            logger.error(
                "Feishu send message failed: HTTP %d %s",
                resp.status_code,
                resp.text[:300],
            )
            return False

        data = resp.json()
        if data.get("code") != 0:
            logger.error(
                "Feishu send message error: %s", data.get("msg", "")
            )
            return False

        logger.info("Group message sent via REST API")
        return True

    def _build_card(self, markdown: str) -> dict:
        """Convert markdown to Feishu interactive card format.

        Splits content by --- to create card sections if needed.
        """
        lines = markdown.split("\n")

        # Extract title from first # heading
        title = "AI+Cloud 每日早报"
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break

        elements = []
        current_md = []

        for line in lines:
            if line.strip() == "---":
                if current_md:
                    elements.append(
                        {"tag": "markdown", "content": "\n".join(current_md).strip()}
                    )
                    current_md = []
                elements.append({"tag": "hr"})
            else:
                current_md.append(line)

        if current_md:
            elements.append(
                {"tag": "markdown", "content": "\n".join(current_md).strip()}
            )

        # Remove trailing hr
        while elements and elements[-1].get("tag") == "hr":
            elements.pop()

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": elements,
        }

        return card
