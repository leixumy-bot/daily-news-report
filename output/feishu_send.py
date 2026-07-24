"""Send daily news digest to Feishu group chat."""

import logging

from .feishu_common import run_lark, run_lark_safe

logger = logging.getLogger("feishu-send")


def send_group_message(
    markdown: str,
    chat_id: str,
    as_bot: str = "bot",
) -> tuple[bool, str]:
    """Send the daily news digest to a Feishu group chat.

    Returns (success, error_message).
    """
    logger.info("Sending group message to chat %s...", chat_id)

    result, err = run_lark_safe(
        [
            "im",
            "+messages-send",
            "--chat-id",
            chat_id,
            "--markdown",
            markdown,
            "--as",
            as_bot,
        ],
        timeout=30,
    )

    if err:
        logger.error("Failed to send group message: %s", err)
        return False, err

    ok = result.get("ok") if result else False
    if ok:
        logger.info("Group message sent successfully")
    else:
        logger.warning("Group message send returned ok=false: %s", result)

    return bool(ok), "" if ok else (result or {}).get("msg", "unknown error")
