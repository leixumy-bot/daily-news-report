"""MCP client for calling local MCP servers via Streamable HTTP."""

import json
import logging
import time
from typing import Any

import requests as req

logger = logging.getLogger("mcp-client")


class MCPClient:
    """Client for a Streamable HTTP MCP server."""

    def __init__(self, server_url: str, client_name: str = "daily-news-report"):
        self.server_url = server_url.rstrip("/") + "/mcp"
        self.client_name = client_name
        self._session_id: str | None = None

    def _initialize(self) -> str | None:
        """Initialize MCP session. Returns session ID."""
        resp = req.post(
            self.server_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": self.client_name, "version": "1.0"},
                },
            },
            timeout=10,
        )
        resp.raise_for_status()
        sid = resp.headers.get("Mcp-Session-Id", "")
        if sid:
            self._session_id = sid

        # Send initialized notification
        if sid:
            req.post(
                self.server_url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                headers={"Mcp-Session-Id": sid},
                timeout=5,
            )
        return sid

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def call_tool(self, name: str, arguments: dict | None = None, tool_timeout: int = 30) -> dict | None:
        """Call an MCP tool. Returns result content dict or None on error."""
        sid = self._initialize() if not self._session_id else self._session_id
        if not sid:
            logger.error("MCP: failed to initialize session")
            return None

        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 100000,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }

        try:
            resp = req.post(
                self.server_url,
                json=payload,
                headers=self._headers(),
                timeout=tool_timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                logger.warning("MCP tool '%s' error: %s", name, data["error"])
                return None

            result = data.get("result", {})
            content = result.get("content", [])
            return content
        except Exception as e:
            logger.warning("MCP tool '%s' call failed: %s", name, e)
            return None

    def extract_text(self, content: list[dict] | None) -> str:
        """Extract text content from MCP tool result."""
        if not content:
            return ""
        texts = []
        for item in content:
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)


class XiaohongshuMCP:
    """Xiaohongshu MCP client wrapper."""

    def __init__(self, server_url: str = "http://localhost:18060"):
        self.client = MCPClient(server_url, "xhs-collector")
        self.logger = logging.getLogger("xhs-mcp")

    def check_login(self) -> tuple[bool, str]:
        """Check if logged in. Returns (is_logged_in, status_text)."""
        content = self.client.call_tool("check_login_status")
        text = self.client.extract_text(content)
        if "已登录" in text or "已登錄" in text:
            return True, text
        return False, text

    def search_feeds(
        self, keyword: str, sort_by: str = "综合", note_type: str = "不限"
    ) -> list[dict]:
        """Search Xiaohongshu feeds. Returns list of feed dicts."""
        content = self.client.call_tool(
            "search_feeds",
            {
                "keyword": keyword,
                "filters": {
                    "sort_by": sort_by,
                    "note_type": note_type,
                    "publish_time": "一周内",
                },
            },
        )
        text = self.client.extract_text(content)

        if not text:
            return []

        try:
            data = json.loads(text)
            feeds = data.get("feeds", [])
            self.logger.info("XHS '%s': found %d feeds", keyword, len(feeds))
            return feeds
        except (json.JSONDecodeError, AttributeError):
            self.logger.warning("XHS search: could not parse response")
            return []

    def get_feed_detail(self, feed_id: str, xsec_token: str) -> str:
        """Get detailed content of a feed."""
        content = self.client.call_tool(
            "get_feed_detail",
            {"feed_id": feed_id, "xsec_token": xsec_token},
        )
        return self.client.extract_text(content)
