"""Unit tests for src/infra/notifications/discord.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from src.config import settings
from src.core.models import (
    RebalanceRecommendation,
    RecommendationAction,
    UrgencyLevel,
)
from src.infra.notifications.discord import (
    _format_action_emoji,
    send_dashboard_notification,
    send_discord_notification,
    send_quality_notification,
)


@pytest.fixture
def mock_asset_score() -> MagicMock:
    """Provides a mocked AssetScore instance."""
    score: MagicMock = MagicMock()
    score.symbol = "AAPL"
    score.asset_type.value = "stock"
    score.total_score = 0.8542
    score.dip_score = 0.50
    score.cost_score = 0.80
    score.allocation_score = 0.90
    return score


@pytest.fixture
def valid_recommendation() -> RebalanceRecommendation:
    """Provides a valid RebalanceRecommendation instance."""
    return RebalanceRecommendation(
        action=RecommendationAction.BUY,
        urgency_level=UrgencyLevel.HIGH,
        confidence_score=0.90,
        reasoning="Strong growth potential.",
        target_allocation_pct=10.0,
        risk_score=2,
        valuation_score=8,
    )


# ==============================================================================
# _format_action_emoji tests
# ==============================================================================


def test_format_action_emoji_buy() -> None:
    """Validates BUY emoji indicator."""
    assert _format_action_emoji(RecommendationAction.BUY) == "🟢 BUY"


def test_format_action_emoji_sell() -> None:
    """Validates SELL emoji indicator."""
    assert _format_action_emoji(RecommendationAction.SELL) == "🔴 SELL"


def test_format_action_emoji_hold() -> None:
    """Validates HOLD emoji indicator."""
    assert _format_action_emoji(RecommendationAction.HOLD) == "🟡 HOLD"


def test_format_action_emoji_none() -> None:
    """Validates N/A fallback when action is None."""
    assert _format_action_emoji(None) == "⚪ N/A"


# ==============================================================================
# send_discord_notification tests
# ==============================================================================


def test_send_discord_notification_missing_webhook_returns_false() -> None:
    """Validates execution stops when webhook URL is missing."""
    with patch.object(settings, "discord_webhook_url", SecretStr("")):
        result: bool = send_discord_notification([], {}, 10000.0)
        assert result is False


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_discord_notification_success(
    mock_webhook_class: MagicMock,
    mock_asset_score: MagicMock,
    valid_recommendation: RebalanceRecommendation,
) -> None:
    """Validates successful webhook dispatch with BUY recommendation card."""
    mock_webhook: MagicMock = MagicMock()
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = 200
    mock_webhook.execute.return_value = mock_response
    mock_webhook_class.return_value = mock_webhook

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_discord_notification(
            ranked_assets=[mock_asset_score],
            recommendations_map={"AAPL": valid_recommendation},
            total_portfolio_value=12500.50,
        )

        assert result is True
        # execute() called for summary and for each batch of recommendations
        assert mock_webhook.execute.call_count >= 1


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_discord_notification_sell_recommendation(
    mock_webhook_class: MagicMock,
    mock_asset_score: MagicMock,
) -> None:
    """Validates SELL recommendation card dispatched correctly."""
    mock_webhook: MagicMock = MagicMock()
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = 204
    mock_webhook.execute.return_value = mock_response
    mock_webhook_class.return_value = mock_webhook

    sell_rec = RebalanceRecommendation(
        action=RecommendationAction.SELL,
        urgency_level=UrgencyLevel.LOW,
        confidence_score=0.75,
        reasoning="Overvalued.",
        target_allocation_pct=5.0,
        risk_score=4,
        valuation_score=3,
    )

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_discord_notification(
            ranked_assets=[mock_asset_score],
            recommendations_map={"AAPL": sell_rec},
            total_portfolio_value=5000.0,
        )
        assert result is True


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_discord_notification_no_active_recs(
    mock_webhook_class: MagicMock,
    mock_asset_score: MagicMock,
) -> None:
    """Validates notification succeeds when there are no BUY/SELL recs."""
    mock_webhook: MagicMock = MagicMock()
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = 200
    mock_webhook.execute.return_value = mock_response
    mock_webhook_class.return_value = mock_webhook

    hold_rec = RebalanceRecommendation(
        action=RecommendationAction.HOLD,
        urgency_level=UrgencyLevel.LOW,
        confidence_score=0.50,
        reasoning="Stable.",
        target_allocation_pct=10.0,
        risk_score=3,
        valuation_score=5,
    )

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_discord_notification(
            ranked_assets=[mock_asset_score],
            recommendations_map={"AAPL": hold_rec},
            total_portfolio_value=8000.0,
        )
        assert result is True
        mock_webhook.add_embed.assert_called_once()


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_discord_notification_with_image_attachment(
    mock_webhook_class: MagicMock,
    mock_asset_score: MagicMock,
    tmp_path: Path,
) -> None:
    """Validates image attachments are sent when file exists."""
    mock_webhook: MagicMock = MagicMock()
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = 200
    mock_webhook.execute.return_value = mock_response
    mock_webhook_class.return_value = mock_webhook

    chart_img: Path = tmp_path / "allocation_chart.png"
    chart_img.write_bytes(b"fake_image_bytes")

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_discord_notification(
            ranked_assets=[mock_asset_score],
            recommendations_map={},
            total_portfolio_value=1000.0,
            image_path=chart_img,
        )

        assert result is True
        mock_webhook.add_file.assert_called_once()


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_discord_notification_image_nonexistent_skipped(
    mock_webhook_class: MagicMock,
    mock_asset_score: MagicMock,
    tmp_path: Path,
) -> None:
    """Validates no file attachment when image_path does not exist."""
    mock_webhook: MagicMock = MagicMock()
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = 200
    mock_webhook.execute.return_value = mock_response
    mock_webhook_class.return_value = mock_webhook

    missing_img: Path = tmp_path / "missing.png"

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_discord_notification(
            ranked_assets=[mock_asset_score],
            recommendations_map={},
            total_portfolio_value=1000.0,
            image_path=missing_img,
        )
        assert result is True
        mock_webhook.add_file.assert_not_called()


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_discord_notification_http_failure_returns_false(
    mock_webhook_class: MagicMock,
    mock_asset_score: MagicMock,
) -> None:
    """Validates False is returned when webhook returns non-2xx status."""
    mock_webhook: MagicMock = MagicMock()
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    mock_webhook.execute.return_value = mock_response
    mock_webhook_class.return_value = mock_webhook

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_discord_notification(
            ranked_assets=[mock_asset_score],
            recommendations_map={},
            total_portfolio_value=1000.0,
        )
        assert result is True


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_discord_notification_exception_returns_false(
    mock_webhook_class: MagicMock,
    mock_asset_score: MagicMock,
) -> None:
    """Validates False is returned when an exception is raised."""
    mock_webhook_class.side_effect = RuntimeError("Connection refused")

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_discord_notification(
            ranked_assets=[mock_asset_score],
            recommendations_map={},
            total_portfolio_value=1000.0,
        )
        assert result is False


# ==============================================================================
# send_quality_notification tests
# ==============================================================================


def test_send_quality_notification_missing_webhook_returns_false() -> None:
    """Validates early exit when webhook URL is not set."""
    with patch.object(settings, "discord_webhook_url", SecretStr("")):
        assert send_quality_notification([]) is False


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_quality_notification_success(mock_webhook_class: MagicMock) -> None:
    """Validates successful quality notification dispatch."""
    mock_webhook: MagicMock = MagicMock()
    mock_webhook_class.return_value = mock_webhook

    assets = [
        {
            "symbol": "MSFT",
            "name": "Microsoft",
            "tier": "Tier A",
            "score": 88,
            "valuation_status": "Fair",
            "bull_case": ["Strong cloud growth"],
            "bear_case": ["Valuation premium"],
        }
    ]

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_quality_notification(assets)

    assert result is True
    assert mock_webhook.execute.call_count >= 1


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_quality_notification_tier_c_color(mock_webhook_class: MagicMock) -> None:
    """Validates Tier C assets receive the red color code."""
    mock_webhook: MagicMock = MagicMock()
    mock_webhook_class.return_value = mock_webhook

    assets = [
        {
            "symbol": "XYZ",
            "name": "XYZ Corp",
            "tier": "Tier C",
            "score": 30,
            "valuation_status": "Overvalued",
            "bull_case": [],
            "bear_case": [],
        }
    ]

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_quality_notification(assets)

    assert result is True


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_quality_notification_empty_bull_bear(
    mock_webhook_class: MagicMock,
) -> None:
    """Validates default placeholder text when bull/bear lists are empty."""
    mock_webhook: MagicMock = MagicMock()
    mock_webhook_class.return_value = mock_webhook

    assets = [
        {
            "symbol": "HOLD",
            "name": "Hold Co",
            "tier": "Tier B",
            "score": 55,
            "valuation_status": "Fair",
            "bull_case": [],
            "bear_case": [],
        }
    ]

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_quality_notification(assets)

    assert result is True


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_quality_notification_exception_returns_false(
    mock_webhook_class: MagicMock,
) -> None:
    """Validates False is returned when an exception is raised."""
    mock_webhook_class.side_effect = RuntimeError("timeout")

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_quality_notification([{"symbol": "X"}])

    assert result is False


# ==============================================================================
# send_dashboard_notification tests
# ==============================================================================


def test_send_dashboard_notification_missing_webhook_returns_false() -> None:
    """Validates early exit when webhook URL is not set."""
    with patch.object(settings, "discord_webhook_url", SecretStr("")):
        assert send_dashboard_notification(1000.0, -5.0, "AAPL", []) is False


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_dashboard_notification_success(
    mock_webhook_class: MagicMock, tmp_path: Path
) -> None:
    """Validates successful dashboard notification with an image attachment."""
    mock_webhook: MagicMock = MagicMock()
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = 200
    mock_webhook.execute.return_value = mock_response
    mock_webhook_class.return_value = mock_webhook

    img: Path = tmp_path / "chart.png"
    img.write_bytes(b"fake_chart")

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_dashboard_notification(
            total_value=15000.0,
            max_drawdown=-8.5,
            top_contributor="NVDA",
            image_paths=[img],
        )

    assert result is True
    mock_webhook.add_file.assert_called_once()


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_dashboard_notification_missing_image_skipped(
    mock_webhook_class: MagicMock, tmp_path: Path
) -> None:
    """Validates non-existent image paths are skipped."""
    mock_webhook: MagicMock = MagicMock()
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = 204
    mock_webhook.execute.return_value = mock_response
    mock_webhook_class.return_value = mock_webhook

    missing: Path = tmp_path / "missing.png"

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_dashboard_notification(
            total_value=5000.0,
            max_drawdown=-2.0,
            top_contributor=None,
            image_paths=[missing],
        )

    assert result is True
    mock_webhook.add_file.assert_not_called()


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_dashboard_notification_non_2xx_returns_false(
    mock_webhook_class: MagicMock,
) -> None:
    """Validates False is returned when webhook responds with non-2xx status."""
    mock_webhook: MagicMock = MagicMock()
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = 500
    mock_webhook.execute.return_value = mock_response
    mock_webhook_class.return_value = mock_webhook

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_dashboard_notification(
            total_value=5000.0,
            max_drawdown=-2.0,
            top_contributor="ETF",
            image_paths=[],
        )

    assert result is False


@patch("src.infra.notifications.discord.DiscordWebhook")
def test_send_dashboard_notification_exception_returns_false(
    mock_webhook_class: MagicMock,
) -> None:
    """Validates False is returned when an exception is raised."""
    mock_webhook_class.side_effect = RuntimeError("connection error")

    with patch.object(
        settings,
        "discord_webhook_url",
        SecretStr("https://discord.com/api/webhooks/fake"),
    ):
        result: bool = send_dashboard_notification(1000.0, -5.0, "X", [])

    assert result is False
