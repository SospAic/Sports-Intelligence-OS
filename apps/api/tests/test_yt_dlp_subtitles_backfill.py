import os
import tempfile

from app.adapters.platforms.yt_dlp import YtDlpAdapter


def test_collect_media_picks_subtitles_and_thumbnail():
    with tempfile.TemporaryDirectory() as root:
        media_dir = os.path.join(root, "acc1")
        vid = "abc123"
        d = os.path.join(media_dir, vid)
        os.makedirs(d)
        open(os.path.join(d, f"{vid}.zh-Hans.vtt"), "w").close()
        open(os.path.join(d, f"{vid}.en.vtt"), "w").close()
        open(os.path.join(d, "thumb.jpg"), "w").close()

        res = YtDlpAdapter._collect_media(root, media_dir, vid)

        assert res is not None
        assert "subtitles" in res
        langs = {s["lang"] for s in res["subtitles"]}
        assert "zh-Hans" in langs and "en" in langs
        assert res["thumbnail"] == "thumb.jpg"


def test_collect_media_returns_none_without_artifacts():
    with tempfile.TemporaryDirectory() as root:
        media_dir = os.path.join(root, "acc1")
        d = os.path.join(media_dir, "vidX")
        os.makedirs(d)
        # No recognizable media files -> None
        open(os.path.join(d, "notes.txt"), "w").close()

        assert YtDlpAdapter._collect_media(root, media_dir, "vidX") is None


def test_collect_media_primary_base_match():
    with tempfile.TemporaryDirectory() as root:
        media_dir = os.path.join(root, "acc1")
        vid = "vidY"
        d = os.path.join(media_dir, vid)
        os.makedirs(d)
        open(os.path.join(d, f"{vid}.mp4"), "w").close()
        open(os.path.join(d, f"{vid}.zh-Hans.vtt"), "w").close()

        res = YtDlpAdapter._collect_media(root, media_dir, vid)
        assert res is not None
        assert res["video"] == f"{vid}.mp4"
        assert res["subtitles"][0]["lang"] == "zh-Hans"
