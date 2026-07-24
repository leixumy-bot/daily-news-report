"""Shared lark-cli subprocess wrapper."""

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("feishu")

LARK_CLI = shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"


def run_lark(args: list[str], timeout: int = 30) -> dict:
    """Run lark-cli command. Returns parsed JSON result.

    Raises RuntimeError on failure.
    """
    env = {
        **os.environ,
        "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
        "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    }
    result = subprocess.run(
        [LARK_CLI] + args + ["--format", "json"],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()[:500]
        raise RuntimeError(
            f"lark-cli failed (exit {result.returncode}): {stderr}"
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"lark-cli output parse failed: {e}")


def run_lark_safe(args: list[str], timeout: int = 30) -> tuple[dict | None, str]:
    """Safe wrapper: returns (result, error_msg). Never raises."""
    try:
        result = run_lark(args, timeout=timeout)
        return result, ""
    except Exception as e:
        return None, str(e)


def run_lark_with_stdin(
    stdin_data: str, args: list[str], timeout: int = 30
) -> tuple[dict | None, str]:
    """Run lark-cli with stdin input. Returns (result, error)."""
    env = {
        **os.environ,
        "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
        "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    }
    try:
        result = subprocess.run(
            [LARK_CLI] + args + ["--format", "json"],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()[:500]
            return None, f"lark-cli failed (exit {result.returncode}): {stderr}"
        return json.loads(result.stdout), ""
    except Exception as e:
        return None, str(e)
