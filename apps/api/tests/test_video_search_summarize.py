from app.services.video_search_summarize import _sentiment, summarize_results


def test_sentiment_neutral_empty():
    assert _sentiment("") == "neutral"


def test_summarize_distribution_and_heuristics():
    payload = {
        "items": [
            {
                "id": "1",
                "title": "精彩夺冠",
                "snippet": "",
                "platform": "youtube",
                "engine": "llm",
                "score": 0.9,
            },
            {
                "id": "2",
                "title": "失败争议",
                "snippet": "",
                "platform": "tiktok",
                "engine": "local",
                "score": 0.7,
            },
            {
                "id": "3",
                "title": "普通训练",
                "snippet": "",
                "platform": "youtube",
                "engine": "llm",
                "score": 0.5,
            },
        ]
    }
    r = summarize_results(payload)
    assert r["total"] == 3
    assert r["platform_distribution"]["youtube"] == 2
    assert r["platform_distribution"]["tiktok"] == 1
    assert r["engine_distribution"]["llm"] == 2
    assert len(r["top_items"]) == 3
    assert r["top_items"][0]["id"] == "1"  # sorted by score desc
    assert r["items"][0]["sentiment"] == "positive"
    assert r["items"][1]["sentiment"] == "negative"
    assert r["items"][2]["sentiment"] == "neutral"
    # heat is clamped/derived from score
    assert r["items"][0]["heat"] == 0.9
    # LLM narrative is reserved; degrades gracefully without a gateway.
    assert r["llm_available"] is False
    assert r["llm_summary"] is None


def test_summarize_empty_items():
    r = summarize_results({"items": []})
    assert r["total"] == 0
    assert r["items"] == []
    assert r["platform_distribution"] == {}
