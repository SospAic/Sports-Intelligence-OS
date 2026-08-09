"""登录墙 / 永久错误必须**快速失败**，不得进入重试放大。

背景：一个登录墙账号（例如未登录态下的 TikTok 主页）此前会经历
「适配器内部重试 → 抛 TransientAdapterError → Celery 判定可重试 → 整轮同步重跑 3 次」，
实测单账号耗时 2m53s，而结果 100% 失败。本文件锁死三条防线：

1. yt-dlp stderr 的永久错误被正确分类为**不可重试**异常，并映射到正确的
   operator 提示码（login_required / permission_denied / not_found）；
2. 命中永久错误时适配器内部**只跑一次** yt-dlp 子进程（不做恢复重试）；
3. 浏览器适配器的每一条真实抓取路径都在导航后调用 ``_check_login_required``，
   且所有 catch-all 包装器都先 ``reraise_if_terminal`` —— AST 级契约测试，
   防止新增抓取路径时漏掉登录墙探测、或把登录墙重新降级成可重试错误。
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

from app.adapters.platforms import yt_dlp as yt_dlp_module
from app.adapters.platforms.base import (
    AdapterNotFoundError,
    LoginRequiredError,
    PermissionDeniedError,
    TransientAdapterError,
)
from app.adapters.platforms.yt_dlp import (
    YTDLP_EXTRACTION_ATTEMPTS,
    YouTubeYtDlpAdapter,
    _is_permanent_extractor_error,
    _permanent_error_for,
)

# ---------------------------------------------------------------------------
# 1) stderr -> 异常分类
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stderr",
    [
        "ERROR: [youtube] xyz: Sign in to confirm you're not a bot. Use --cookies-from-browser",
        "ERROR: [youtube] xyz: Sign in to confirm your age",
        "ERROR: [tiktok] Login required to view this account",
        "ERROR: Private video. Sign in if you've been granted access",
        "ERROR: [instagram] This is a private account",
        "ERROR: solve the captcha to continue",
        "ERROR: This video is members-only content",
    ],
)
def test_login_wall_stderr_maps_to_login_required(stderr: str) -> None:
    err = _permanent_error_for("youtube", stderr)
    assert isinstance(err, LoginRequiredError)
    assert err.code == "login_required"
    assert err.retryable is False


@pytest.mark.parametrize(
    "stderr",
    [
        "ERROR: The uploader has not made this video available in your country",
        "ERROR: Video blocked on copyright grounds",
        "ERROR: Your IP address is blocked by the platform",
        "ERROR: You do not have permission to access this resource",
    ],
)
def test_forbidden_stderr_maps_to_permission_denied(stderr: str) -> None:
    err = _permanent_error_for("youtube", stderr)
    assert isinstance(err, PermissionDeniedError)
    assert err.code == "permission_denied"
    assert err.retryable is False


@pytest.mark.parametrize(
    "stderr",
    [
        "ERROR: [youtube] abc: Video unavailable",
        "ERROR: This video has been removed by the uploader",
        "ERROR: This account has been terminated",
        "ERROR: Unsupported URL: https://example.com/foo",
        "ERROR: HTTP Error 404: Not Found",
    ],
)
def test_gone_stderr_maps_to_not_found(stderr: str) -> None:
    err = _permanent_error_for("youtube", stderr)
    assert isinstance(err, AdapterNotFoundError)
    assert err.code == "not_found"
    assert err.retryable is False


@pytest.mark.parametrize(
    "stderr",
    [
        "ERROR: unable to download webpage: [Errno 111] Connection refused",
        "ERROR: Unable to extract webpage video data",
        "WARNING: unable to download video info webpage: HTTP Error 500",
        "",
    ],
)
def test_transient_stderr_is_not_classified_permanent(stderr: str) -> None:
    """真正的网络抖动必须保持可重试，否则会把可恢复失败变成硬失败。"""
    assert _permanent_error_for("youtube", stderr) is None
    assert _is_permanent_extractor_error(stderr) is False


def test_permanent_error_message_carries_the_original_stderr() -> None:
    err = _permanent_error_for("tiktok", "ERROR: Login required for this account")
    assert err is not None
    assert "Login required" in str(err)


# ---------------------------------------------------------------------------
# 2) 永久错误只跑一次子进程（速度防线）
# ---------------------------------------------------------------------------


class _FakeProc:
    """最小 asyncio 子进程替身。

    刻意不暴露 ``stdout`` / ``stderr`` 属性，这样 ``_communicate_with_timeout``
    会走它自带的「简单 collect」分支，无需 mock 该方法本身。
    """

    def __init__(self, stderr: bytes) -> None:
        self.returncode = 1
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self._stderr


def _patch_subprocess(monkeypatch: pytest.MonkeyPatch, stderr: bytes) -> list[str]:
    """把 yt-dlp 子进程换成固定失败的替身，并记录每次启动。"""
    calls: list[str] = []

    async def _fake_exec(*args: object, **_kwargs: object) -> _FakeProc:
        calls.append(str(args[-1]) if args else "")
        return _FakeProc(stderr)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    # 退避降到 0，即便走到重试分支测试也不会真的等待。
    monkeypatch.setattr(yt_dlp_module, "YTDLP_ATTEMPT_BACKOFF_SECONDS", (0.0, 0.0))
    return calls


async def test_login_wall_fails_after_a_single_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = b"ERROR: [youtube] c1: Sign in to confirm you're not a bot"
    calls = _patch_subprocess(monkeypatch, stderr)
    adapter = YouTubeYtDlpAdapter()

    with pytest.raises(LoginRequiredError) as excinfo:
        await adapter._run_yt_dlp("https://www.youtube.com/@x/videos")

    assert excinfo.value.retryable is False
    assert len(calls) == 1, "登录墙不得触发适配器内部恢复重试"


async def test_transient_failure_still_uses_the_recovery_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对照组：非永久失败仍然享受恢复重试，避免修复把可恢复场景一并砍掉。"""
    stderr = b"ERROR: unable to download webpage: [Errno 111] Connection refused"
    calls = _patch_subprocess(monkeypatch, stderr)
    adapter = YouTubeYtDlpAdapter()

    with pytest.raises(TransientAdapterError):
        await adapter._run_yt_dlp("https://www.youtube.com/@x/videos")

    assert len(calls) == max(1, YTDLP_EXTRACTION_ATTEMPTS)


async def test_gone_channel_fails_fast_as_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_subprocess(monkeypatch, b"ERROR: [youtube] c1: Video unavailable")
    adapter = YouTubeYtDlpAdapter()

    with pytest.raises(AdapterNotFoundError):
        await adapter._run_yt_dlp("https://www.youtube.com/@x/videos")

    assert len(calls) == 1


async def test_account_json_path_also_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """账号元数据抽取（_run_yt_dlp_single）走的是另一段循环，同样必须快速失败。"""
    calls = _patch_subprocess(monkeypatch, b"ERROR: [tiktok] user: Login required")
    adapter = YouTubeYtDlpAdapter()

    with pytest.raises(LoginRequiredError):
        await adapter._run_yt_dlp_single("https://www.tiktok.com/@x")

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# 3) 浏览器适配器抓取路径必须探测登录墙（AST 契约）
# ---------------------------------------------------------------------------

_ADAPTERS_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "adapters" / "platforms"

# 四平台 × 四条真实抓取路径。这些方法都会导航到公开页，任何一条漏掉登录墙探测，
# 都会让登录墙以「解析失败」的面目出现并被当成可重试错误。
_BROWSER_MODULES = (
    "youtube_browser.py",
    "tiktok_browser.py",
    "douyin_browser.py",
    "bilibili_browser.py",
)
_GUARDED_METHODS = (
    "resolve_account",
    "fetch_account_analytics",
    "list_contents",
    "fetch_content",
)


def _methods_calling(path: pathlib.Path, attr: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                func = inner.func
                name = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else func.id
                    if isinstance(func, ast.Name)
                    else ""
                )
                if name == attr:
                    found.add(node.name)
                    break
    return found


@pytest.mark.parametrize("module_name", _BROWSER_MODULES)
@pytest.mark.parametrize("method_name", _GUARDED_METHODS)
def test_browser_fetch_paths_probe_the_login_wall(module_name: str, method_name: str) -> None:
    path = _ADAPTERS_DIR / module_name
    assert path.exists(), f"missing adapter module: {module_name}"
    guarded = _methods_calling(path, "_check_login_required")
    assert method_name in guarded, (
        f"{module_name}::{method_name} 未调用 _check_login_required —— "
        "登录墙会退化成可重试的解析失败并浪费 3 倍同步时长"
    )


@pytest.mark.parametrize("module_name", _BROWSER_MODULES)
def test_catch_all_wrappers_reraise_terminal_errors(module_name: str) -> None:
    """``except Exception: raise TransientAdapterError`` 必须先放行终止性错误。

    否则上面补的登录墙探测会被同一函数的 catch-all 重新包成可重试错误，
    修复等于没做。
    """
    tree = ast.parse((_ADAPTERS_DIR / module_name).read_text(encoding="utf-8"))
    offenders: list[int] = []
    for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)):
        raises_transient = any(
            isinstance(n, ast.Raise)
            and isinstance(n.exc, ast.Call)
            and isinstance(n.exc.func, ast.Name)
            and n.exc.func.id == "TransientAdapterError"
            for n in ast.walk(handler)
        )
        if not raises_transient:
            continue
        guards = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "reraise_if_terminal"
            for n in ast.walk(handler)
        )
        if not guards:
            offenders.append(handler.lineno)
    assert not offenders, (
        f"{module_name} 第 {offenders} 行的 catch-all 未调用 reraise_if_terminal，"
        "登录墙会被重新降级为可重试错误"
    )


def test_tiktok_anti_scrape_raises_login_required() -> None:
    """TikTok 公开页被反爬拦截时抛的是 login_required（这正是 2m53s 的根因）。"""
    tree = ast.parse((_ADAPTERS_DIR / "tiktok_browser.py").read_text(encoding="utf-8"))
    login_raises = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Raise)
        and isinstance(n.exc, ast.Call)
        and isinstance(n.exc.func, ast.Name)
        and n.exc.func.id == "LoginRequiredError"
    ]
    # 登录流程 1 处 + 资料/指标反爬拦截各 1 处。
    assert len(login_raises) >= 3, "TikTok 反爬拦截应抛 LoginRequiredError 而非可重试异常"


# ---------------------------------------------------------------------------
# 4) 四平台 resolve_account 必须识别「反爬空壳页」（AST 契约）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _BROWSER_MODULES)
def test_resolve_account_detects_anti_bot_shell(module_name: str) -> None:
    """空壳页（HTTP 200 但无权威 payload、无真实名字）必须快速失败。

    这类页面不抛异常，`_check_login_required` 也探测不到（没有登录跳转、
    没有登录弹窗），适配器会带着占位名（``的抖音`` / ``UID 123`` / ``@handle``）
    正常返回 —— 同步被记为 degraded 且可重试，于是每次调度都要重新付出
    「页面加载 + 指标超时 + 作品分页」的完整浏览器开销（抖音实测 126s）。
    """
    path = _ADAPTERS_DIR / module_name
    guarded = _methods_calling(path, "is_anti_bot_shell_profile")
    assert "resolve_account" in guarded, (
        f"{module_name}::resolve_account 未调用 is_anti_bot_shell_profile —— "
        "反爬空壳页会被当作成功抓取并写入占位账号名"
    )
