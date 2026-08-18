from types import SimpleNamespace

from pydantic import SecretStr

from app.adapters.platforms.base import AdapterCapability
from app.core.config import Settings
from app.schemas.readiness import PlatformCanaryRead
from app.schemas.settings import PlatformCredentialRead
from app.services.readiness import build_feature_readiness, build_platform_readiness
from app.services.settings import _secret_configured


def _credential(**overrides: object) -> PlatformCredentialRead:
    payload: dict[str, object] = {
        "platform_key": "youtube",
        "mode": "api",
        "source": "environment",
        "enabled": True,
        "configured": True,
        "configured_fields": ["api_key"],
        "config_masked": {"api_key": "configured"},
        "updated_at": None,
    }
    payload.update(overrides)
    return PlatformCredentialRead.model_validate(payload)


def _descriptor() -> SimpleNamespace:
    return SimpleNamespace(
        implementation_status="implemented",
        capabilities={
            AdapterCapability.PUBLIC_PROFILE: True,
            AdapterCapability.ACCOUNT_ANALYTICS: True,
            AdapterCapability.CONTENT_ANALYTICS: True,
        },
        source_kinds=frozenset({"live"}),
    )


def test_configured_platform_is_unverified_until_a_live_probe() -> None:
    item = build_platform_readiness(
        platform=SimpleNamespace(
            key="youtube", name="YouTube", adapter_key="youtube_ytdlp"
        ),
        adapter_descriptor=_descriptor(),
        credential=_credential(),
    )

    assert item.status == "unverified"
    assert item.credential_source == "environment"
    assert item.missing_configuration == []
    assert any("实时探针" in condition for condition in item.conditions)


def test_incomplete_api_configuration_exposes_required_fields_without_secrets() -> None:
    item = build_platform_readiness(
        platform=SimpleNamespace(
            key="tiktok", name="TikTok", adapter_key="tiktok_ytdlp"
        ),
        adapter_descriptor=_descriptor(),
        credential=_credential(
            platform_key="tiktok",
            configured=False,
            configured_fields=["client_key"],
            config_masked={"client_key": "configured"},
        ),
    )

    assert item.status == "needs_setup"
    assert "client_secret" in item.missing_configuration
    assert "access_token" in item.missing_configuration
    assert "client_secret" not in item.detail


def test_passed_probe_promotes_configured_platform_to_ready() -> None:
    item = build_platform_readiness(
        platform=SimpleNamespace(
            key="youtube", name="YouTube", adapter_key="youtube"
        ),
        adapter_descriptor=_descriptor(),
        credential=_credential(),
        last_probe=PlatformCanaryRead(
            platform_key="youtube",
            adapter_key="youtube",
            trigger="manual",
            mode="api",
            credential_source="environment",
            status="passed",
            checked_at="2026-08-17T00:00:00Z",
            detail="平台探针通过",
        ),
    )

    assert item.status == "ready"
    assert item.last_probe is not None


def test_feature_readiness_keeps_private_analytics_and_keyframes_blocked() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        semantic_search_enabled=True,
        embedding_backend="tei",
        video_search_enabled=True,
        video_search_analyzer="gemini_video",
        gemini_api_key=SecretStr("gemini-test"),
    )

    features = {item.key: item for item in build_feature_readiness(settings)}

    assert features["channel_resource_permissions"].status == "blocked"
    assert features["private_analytics_and_experiments"].status == "blocked"
    assert features["keyframe_multimodal_index"].status == "blocked"
    assert features["semantic_text_search"].status == "unverified"
    assert "关键帧" in features["keyframe_multimodal_index"].detail


def test_runtime_secret_flag_requires_non_empty_secret_content() -> None:
    assert _secret_configured(SecretStr("  ")) is False
    assert _secret_configured(SecretStr("configured")) is True
    assert _secret_configured(None) is False
