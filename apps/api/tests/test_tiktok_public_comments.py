from datetime import UTC, datetime

from app.adapters.platforms.tiktok_browser import TikTokBrowserAdapter


def test_tiktok_public_comment_payload_is_normalized_with_real_details() -> None:
    payload = {
        "comments": [
            {
                "cid": "7667443096184013598",
                "text": "Could've just said lightning at the beginning",
                "digg_count": 8,
                "reply_comment_total": 2,
                "create_time": 1785215766,
                "reply_id": "0",
                "user": {
                    "nickname": "Commenter",
                    "unique_id": "commenter01",
                    "avatar_thumb": {"url_list": ["https://example.test/avatar.jpg"]},
                },
            }
        ]
    }

    rows = TikTokBrowserAdapter._normalize_public_comments(payload)

    assert rows == [
        {
            "platform_comment_id": "7667443096184013598",
            "author_name": "Commenter",
            "author_url": "https://www.tiktok.com/@commenter01",
            "author_avatar_url": "https://example.test/avatar.jpg",
            "text": "Could've just said lightning at the beginning",
            "like_count": 8,
            "reply_count": 2,
            "parent_comment_id": None,
            "is_reply": False,
            "published_at": datetime.fromtimestamp(1785215766, tz=UTC),
        }
    ]


def test_tiktok_public_comment_normalization_skips_empty_rows_and_caps_at_20() -> None:
    payload = {
        "comments": [
            {"cid": "", "text": "discard"},
            *[
                {
                    "cid": str(index),
                    "text": f"comment {index}",
                    "user": {"nickname": "user"},
                }
                for index in range(25)
            ],
        ]
    }

    rows = TikTokBrowserAdapter._normalize_public_comments(payload, limit=20)

    assert len(rows) == 20
    assert rows[0]["platform_comment_id"] == "0"
    assert rows[-1]["platform_comment_id"] == "19"
