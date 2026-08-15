from datetime import UTC, datetime

from app.adapters.platforms.base import AdapterCallContext
from app.adapters.platforms.tiktok_browser import (
    TikTokBrowserAdapter,
    _profile_pagination_window,
)


def _ctx() -> AdapterCallContext:
    return AdapterCallContext(
        config={},
        observed_at=datetime.now(UTC),
        request_id="tiktok-post-mapping-test",
    )


def test_tiktok_profile_pagination_keeps_second_page_materialized() -> None:
    # The sync engine asks for a larger window, but TikTok's public endpoint
    # currently yields 15 items. The second cursor page must therefore request
    # the next 15-item slice and scroll far enough to materialize it.
    assert _profile_pagination_window(0, 50) == (15, 10)
    assert _profile_pagination_window(15, 50) == (15, 15)


def test_structured_post_mapping_keeps_caption_and_metrics_separate() -> None:
    item = TikTokBrowserAdapter._post_to_content(
        {
            "id": "video-1",
            "desc": "A real caption",
            "createTime": 1_700_000_000,
            "stats": {"playCount": 6101, "diggCount": 123, "commentCount": 9},
            "video": {
                "duration": 12,
                "cover": {"urlList": ["https://img.test/1.jpg"]},
            },
        },
        "creator",
        _ctx(),
        0,
    )

    assert item.title == "A real caption"
    assert item.cover_url == "https://img.test/1.jpg"
    assert item.metadata["view_count"] == 6101
    assert item.metadata["like_count"] == 123
    assert item.metadata["comment_count"] == 9
    assert item.metadata["title_unavailable"] is False


def test_structured_post_mapping_never_uses_view_count_as_title() -> None:
    item = TikTokBrowserAdapter._post_to_content(
        {"id": "video-2", "desc": "", "stats": {"playCount": 6101}},
        "creator",
        _ctx(),
        0,
    )

    assert item.title.endswith("video-2")
    assert item.title != "6101"
    assert item.metadata["view_count"] == 6101
    assert item.metadata["title_unavailable"] is True


def test_structured_photo_post_mapping_keeps_cover() -> None:
    item = TikTokBrowserAdapter._post_to_content(
        {
            "id": "photo-1",
            "desc": "A carousel caption",
            "imagePost": {
                "images": [
                    {"imageURL": {"urlList": ["https://img.test/photo-1.jpg"]}}
                ]
            },
        },
        "creator",
        _ctx(),
        0,
    )

    assert item.cover_url == "https://img.test/photo-1.jpg"
