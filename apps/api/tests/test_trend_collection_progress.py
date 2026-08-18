"""Contract tests for the live trend-collection progress channel."""

from __future__ import annotations

from app.tasks.trends import _TrendProgressReporter


class _FakeCeleryTask:
    def __init__(self) -> None:
        self.states: list[dict[str, object]] = []

    def update_state(self, *, state: str, meta: dict[str, object]) -> None:
        self.states.append({"state": state, "meta": meta})


def test_trend_progress_log_is_bounded_and_keeps_latest_state() -> None:
    task = _FakeCeleryTask()
    reporter = _TrendProgressReporter(task, "workspace-1")

    for index in range(125):
        reporter.emit(f"阶段 {index}", "collecting")

    assert len(task.states) == 125
    assert len(reporter.log) == 120
    assert reporter.log[0]["message"] == "阶段 5"
    assert reporter.log[-1]["message"] == "阶段 124"
    latest = task.states[-1]
    assert latest["state"] == "PROGRESS"
    assert latest["meta"]["workspace_id"] == "workspace-1"  # type: ignore[index]
    assert latest["meta"]["stage"] == "collecting"  # type: ignore[index]
    assert latest["meta"]["log"] == reporter.log  # type: ignore[index]


def test_trend_progress_reporter_marks_failures_as_error() -> None:
    task = _FakeCeleryTask()
    reporter = _TrendProgressReporter(task, None)

    reporter.emit("采集失败：broker 不可用", "failed")

    assert reporter.log[-1]["level"] == "error"
    assert task.states[-1]["meta"]["stage"] == "failed"  # type: ignore[index]
