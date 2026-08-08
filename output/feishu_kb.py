"""Create knowledge base document for daily report."""

import logging

logger = logging.getLogger("feishu-kb")


def create_kb_doc(
    markdown_content: str,
    title: str,
    as_user: str = "user",
    wiki_space_id: str = "my_library",
) -> tuple[dict | None, str]:
    """Create a KB doc with the full report.

    Returns (result_dict, error_message). result_dict contains:
      - url: the doc URL
      - document_id: the doc token

    Strategy:
    1. Create the doc via `docs +create` with markdown content
    2. Return the URL (user can organize into wiki manually)
    """
    logger.info("Creating KB doc '%s'...", title)

    # Step 1: Create a doc with markdown content via stdin pipe
    # --content - reads from stdin, avoids file path issues
    from .feishu_common import run_lark_with_stdin

    result, err = run_lark_with_stdin(
        stdin_data=markdown_content,
        args=[
            "docs",
            "+create",
            "--title",
            title,
            "--doc-format",
            "markdown",
            "--content",
            "-",
            "--parent-position",
            wiki_space_id,
            "--as",
            as_user,
        ],
        timeout=30,
    )

    if err:
        logger.error("Failed to create KB doc: %s", err)
        return None, err

    # Handle nested data structure from `docs +create`
    data = (result or {}).get("data", {})
    doc_data = data.get("document", {})
    doc_url = doc_data.get("url", data.get("url", ""))
    doc_id = doc_data.get("document_id", data.get("document_id", ""))

    if not doc_url:
        logger.warning("KB doc created but no URL returned: %s", result)

    logger.info("KB doc created: %s", doc_url)

    return result, ""
