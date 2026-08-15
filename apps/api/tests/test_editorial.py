from datetime import UTC, datetime

import pytest

from app.schemas.editorial import EditorialBulkUpdate, EditorialItemUpdate, EditorialSavedViewCreate
from app.services.editorial import can_transition


def test_editorial_transition_matrix_keeps_approval_explicit() -> None:
    assert can_transition("draft", "in_review")
    assert can_transition("in_review", "approved")
    assert can_transition("in_review", "rejected")
    assert can_transition("rejected", "draft")
    assert not can_transition("draft", "approved")
    assert not can_transition("approved", "draft")
    assert not can_transition("archived", "in_review")


def test_editorial_update_requires_a_field_and_accepts_clearable_values() -> None:
    with pytest.raises(ValueError, match="至少提供"):
        EditorialItemUpdate()

    payload = EditorialItemUpdate(
        assignee_id=None,
        due_at=datetime.now(UTC),
        review_note="请核对来源",
    )
    assert payload.assignee_id is None
    assert payload.due_at is not None
    assert payload.review_note == "请核对来源"


def test_editorial_update_rejects_out_of_range_priority() -> None:
    with pytest.raises(ValueError):
        EditorialItemUpdate(priority=101)


def test_editorial_bulk_update_requires_items_and_a_change() -> None:
    with pytest.raises(ValueError):
        EditorialBulkUpdate(item_ids=[])
    with pytest.raises(ValueError, match="批量更新至少"):
        EditorialBulkUpdate(item_ids=["00000000-0000-0000-0000-000000000001"])

    payload = EditorialBulkUpdate(
        item_ids=["00000000-0000-0000-0000-000000000001"],
        assignee_id=None,
    )
    assert payload.assignee_id is None


def test_editorial_saved_view_validates_priority_range() -> None:
    with pytest.raises(ValueError, match="最低优先级"):
        EditorialSavedViewCreate(name="高优先级", priority_min=90, priority_max=10)
