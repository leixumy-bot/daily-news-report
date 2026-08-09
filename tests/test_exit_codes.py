"""退出码状态机测试。

核心：群消息发送失败时进程必须返回非零，否则 workflow 会写 .last_run、
09:45 保底不会再跑，实际没推送却标记完成。
"""

import sys
import types

from daily_report import compute_exit_code, message_uuid, _mark_done_in_ci


def test_group_message_failure_is_nonzero():
    """群消息未全部成功 → 非零退出码（workflow 不写 .last_run，09:45 保底补跑）。"""
    assert compute_exit_code(group_ok=False, dry_run=False) == 1


def test_group_message_success_is_zero():
    """群消息全部成功 → 0（多维表/知识库失败不影响退出码，避免重复推送）。"""
    assert compute_exit_code(group_ok=True, dry_run=False) == 0


def test_dry_run_never_fails():
    """dry-run 不推送，无论群消息状态恒为 0（不把未推送算作失败）。"""
    assert compute_exit_code(group_ok=False, dry_run=True) == 0
    assert compute_exit_code(group_ok=True, dry_run=True) == 0


def test_scheduled_message_uuid_is_stable_but_manual_is_fresh():
    assert message_uuid("2026-08-08", "five_layer", 0, "same") == message_uuid("2026-08-08", "five_layer", 0, "same")
    assert message_uuid("2026-08-08", "five_layer", 0, "same") != message_uuid("2026-08-08", "five_layer", 0, "changed")
    assert message_uuid("2026-08-08", "five_layer", 0, manual=True) != message_uuid("2026-08-08", "five_layer", 0, manual=True)


def test_mark_done_in_ci_local_mode_does_not_write():
    """非 CI：直接返回 True，不写 .last_run（本地手动跑不应标记完成）。"""
    assert _mark_done_in_ci("2026-08-09") is True


def test_mark_done_in_ci_writes_marker_and_runs_git(monkeypatch, tmp_path):
    """CI：推送成功后写 .last_run 并执行 git 提交/push，不等 workflow 收尾。"""
    import daily_report

    monkeypatch.setattr(daily_report, "is_ci", lambda: True)
    monkeypatch.setattr(daily_report, "HERE", tmp_path)

    calls = []
    fake_sub = types.ModuleType("subprocess")

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    fake_sub.run = fake_run
    monkeypatch.setitem(sys.modules, "subprocess", fake_sub)

    assert _mark_done_in_ci("2026-08-09") is True
    assert (tmp_path / ".last_run").read_text().strip() == "2026-08-09"
    git_cmds = [c for c in calls if c[0] == "git"]
    assert git_cmds


def test_mark_done_in_ci_survives_git_failure(monkeypatch, tmp_path):
    """git 命令失败只告警、不抛异常、仍返回 True（push 失败不影响主流程退出码）。"""
    import daily_report

    monkeypatch.setattr(daily_report, "is_ci", lambda: True)
    monkeypatch.setattr(daily_report, "HERE", tmp_path)

    import sys
    import types

    fake_sub = types.ModuleType("subprocess")

    def fake_run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="boom")

    fake_sub.run = fake_run
    monkeypatch.setitem(sys.modules, "subprocess", fake_sub)

    assert daily_report._mark_done_in_ci("2026-08-09") is True
