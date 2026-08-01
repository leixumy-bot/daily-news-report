"""退出码状态机测试。

核心：群消息发送失败时进程必须返回非零，否则 workflow 会写 .last_run、
11:30 保底不会再跑，实际没推送却标记完成。
"""

from daily_report import compute_exit_code


def test_group_message_failure_is_nonzero():
    """群消息未全部成功 → 非零退出码（workflow 不写 .last_run，保底补跑）。"""
    assert compute_exit_code(group_ok=False, dry_run=False) == 1


def test_group_message_success_is_zero():
    """群消息全部成功 → 0（多维表/知识库失败不影响退出码，避免重复推送）。"""
    assert compute_exit_code(group_ok=True, dry_run=False) == 0


def test_dry_run_never_fails():
    """dry-run 不推送，无论群消息状态恒为 0（不把未推送算作失败）。"""
    assert compute_exit_code(group_ok=False, dry_run=True) == 0
    assert compute_exit_code(group_ok=True, dry_run=True) == 0
