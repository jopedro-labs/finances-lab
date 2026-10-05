"""Infrastructure module for dispatching opportunity_evaluation
alerts to Discord webhooks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from discord_webhook import DiscordEmbed, DiscordWebhook  # type: ignore[import-untyped]

from src.config import settings
from src.core.models import RebalanceRecommendation, RecommendationAction
from src.core.opportunity_evaluation.base import AssetScore
from src.utils.logger.logger import logger

COLOR_GREEN: int = 0x2ECC71
COLOR_RED: int = 0xE74C3C
COLOR_BLUE: int = 0x3498DB


def _format_action_emoji(action: RecommendationAction | None) -> str:
    """Returns visual emoji indicators for AI recommendation actions."""
    if action == RecommendationAction.BUY:
        return "🟢 BUY"
    if action == RecommendationAction.SELL:
        return "🔴 SELL"
    if action == RecommendationAction.HOLD:
        return "🟡 HOLD"
    return "⚪ N/A"


def send_quality_notification(evaluated_assets: list[dict[str, Any]]) -> bool:
    """Dispatches a summary of asset quality tiers and scores to Discord."""
    webhook_url: str = settings.discord_webhook_url.get_secret_value()
    if not webhook_url:
        return False

    try:
        webhook = DiscordWebhook(url=webhook_url, username="Project Finance Bot")

        embed = DiscordEmbed(
            title="💎 Portfolio Quality Analysis Summary",
            description="Fundamental health and quality tier evaluation.",
            color=f"{COLOR_BLUE:06x}",
        )

        matrix_lines: list[str] = [
            "```text",
            f"{'Symbol':<10} {'Tier':<8} {'Score':>5} {'Valuation':<12}",
            "─" * 40,
        ]

        for item in evaluated_assets:
            matrix_lines.append(
                f"{item['symbol']:<10} "
                f"{item['tier']:<8} "
                f"{item['score']:>5} "
                f"{item['valuation_status']:<12}"
            )

        matrix_lines.append("```")
        embed.add_embed_field(
            name="📋 Quality Matrix", value="\n".join(matrix_lines), inline=False
        )

        webhook.add_embed(embed)
        webhook.execute()

        # Detailed Asset Diagnostics Cards in batches
        for i in range(0, len(evaluated_assets), 9):
            batch_webhook = DiscordWebhook(
                url=webhook_url, username="Project Finance Bot"
            )
            batch = evaluated_assets[i : i + 9]

            for item in batch:
                tier: str = str(item.get("tier", "Tier B"))
                color_code: int = COLOR_BLUE
                if "Tier A" in tier:
                    color_code = COLOR_GREEN
                elif "Tier C" in tier:
                    color_code = COLOR_RED

                diag_embed = DiscordEmbed(
                    title=f"💎 {item['name']} ({item['symbol']})",
                    color=f"{color_code:06x}",
                )

                bull_list = "\n".join([f"• {b}" for b in item.get("bull_case", [])])
                bear_list = "\n".join([f"• {b}" for b in item.get("bear_case", [])])

                # Sane default if bull/bear lists are empty to avoid 400 error
                bull_content = (
                    bull_list if bull_list.strip() else "• No catalysts identified."
                )
                bear_content = (
                    bear_list if bear_list.strip() else "• No risks identified."
                )

                content = (
                    f"**Tier:** `{tier}`  │  **Score:** `{item['score']}/100`\n"
                    f"**Valuation:** `{item['valuation_status']}`\n"
                    f"─────────────────────────────────────────\n"
                    f"**🟢 Bull Case:**\n{bull_content}\n"
                    f"**🔴 Bear Case:**\n{bear_content}"
                )
                diag_embed.set_description(content)
                batch_webhook.add_embed(diag_embed)

            batch_webhook.execute()

        return True
    except Exception as err:
        logger.error(f"Failed to send quality notification: {err}")
        return False


def send_dashboard_notification(
    total_value: float,
    max_drawdown: float,
    top_contributor: str | None,
    image_paths: list[Path],
) -> bool:
    """Dispatches dashboard overview and charts to Discord."""
    webhook_url: str = settings.discord_webhook_url.get_secret_value()
    if not webhook_url:
        return False

    try:
        webhook = DiscordWebhook(url=webhook_url, username="Project Finance Bot")

        embed = DiscordEmbed(
            title="📈 Portfolio Performance Dashboard",
            description=(
                f"💰 **Total Value:** `{total_value:,.2f} EUR`\n"
                f"📉 **Max Drawdown:** `{max_drawdown:.2f}%`\n"
                f"🚀 **Top Contributor:** `{top_contributor or 'N/A'}`"
            ),
            color=f"{COLOR_GREEN:06x}",
        )
        webhook.add_embed(embed)

        # Attach Performance Charts
        for img_path in image_paths:
            if img_path.exists():
                with open(img_path, "rb") as f:
                    webhook.add_file(file=f.read(), filename=img_path.name)

        response = webhook.execute()
        return response.status_code in (200, 204)
    except Exception as err:
        logger.error(f"Failed to send dashboard notification: {err}")
        return False


def send_discord_notification(
    ranked_assets: list[AssetScore],
    recommendations_map: dict[str, RebalanceRecommendation],
    total_portfolio_value: float,
    image_path: Path | None = None,
) -> bool:
    """Dispatches opportunity_evaluation summary, matrix, and
    action cards to Discord.
    """
    webhook_url: str = settings.discord_webhook_url.get_secret_value()
    if not webhook_url:
        logger.warning("Discord webhook URL is not configured in settings. Skipping.")
        return False

    try:
        webhook = DiscordWebhook(url=webhook_url, username="Project Finance Bot")

        # Main Portfolio & Decision Strategy Embed
        stock_weights: str = (
            f"Dip: `{settings.stock_weight_dip:.2f}` | "
            f"Fwd P/E: `{settings.stock_weight_forward_pe:.2f}` | "
            f"52w Range: `{settings.stock_weight_52w_range:.2f}` | "
            f"Gap: `{settings.stock_weight_allocation:.2f}`"
        )
        etf_weights: str = (
            f"Dip: `{settings.etf_weight_dip:.2f}` | "
            f"TER/Cost: `{settings.etf_weight_ter:.2f}` | "
            f"Gap: `{settings.etf_weight_allocation:.2f}`"
        )

        main_embed = DiscordEmbed(
            title="📊 Portfolio Rebalance & Decision Strategy Summary",
            description=(
                f"💰 **Total Portfolio Value:** `{total_portfolio_value:,.2f} EUR`\n"
                f"🎯 **Target Assets Evaluated:** `{len(ranked_assets)}`"
            ),
            color=f"{COLOR_BLUE:06x}",
        )

        main_embed.add_embed_field(
            name="⚖️ Active Decision Strategy Weights",
            value=(
                f"• **Stocks Formula:** {stock_weights}\n"
                f"• **ETFs Formula:** {etf_weights}"
            ),
            inline=False,
        )

        # Build Untruncated Decision Matrix Text
        hdr: str = (
            f"{'Rank':<4} {'Symbol':<10} {'Type':<6} " f"{'Score':>7} {'AI Action':<9}"
        )
        matrix_lines: list[str] = [
            "```text",
            hdr,
            "─" * 40,
        ]

        score_map: dict[str, AssetScore] = {s.symbol: s for s in ranked_assets}

        for rank, score in enumerate(ranked_assets, start=1):
            rec: RebalanceRecommendation | None = recommendations_map.get(score.symbol)
            act_str: str = rec.action.value.upper() if rec and rec.action else "N/A"

            matrix_lines.append(
                f"{rank:<4} "
                f"{score.symbol:<10} "
                f"{score.asset_type.value.upper():<6} "
                f"{score.total_score:>7.3f} "
                f"{act_str:<9}"
            )

        matrix_lines.append("```")
        main_embed.add_embed_field(
            name="📋 Investment Decision Matrix",
            value="\n".join(matrix_lines),
            inline=False,
        )

        webhook.add_embed(main_embed)

        # Attach Allocation Chart Image to the first message if it exists
        if image_path and image_path.exists():
            with open(image_path, "rb") as img_file:
                webhook.add_file(file=img_file.read(), filename=image_path.name)

        webhook.execute()

        # Generate Actionable Advisory Insights Cards in batches of 9
        # (Discord allows max 10 embeds per message, we use 9 for safety)
        active_recs: list[tuple[str, RebalanceRecommendation]] = [
            (sym, r)
            for sym, r in recommendations_map.items()
            if r.action in (RecommendationAction.BUY, RecommendationAction.SELL)
        ]

        if active_recs:
            for i in range(0, len(active_recs), 9):
                batch_webhook = DiscordWebhook(
                    url=webhook_url, username="Project Finance Bot"
                )
                batch = active_recs[i : i + 9]

                for symbol, rec in batch:
                    score_info: AssetScore | None = score_map.get(symbol)
                    action_text: str = _format_action_emoji(rec.action)
                    urgency_text: str = (
                        rec.urgency_level.value.upper() if rec.urgency_level else "N/A"
                    )
                    conf_text: str = f"{rec.confidence_score * 100:.0f}%"

                    color_code: int = (
                        COLOR_GREEN
                        if rec.action == RecommendationAction.BUY
                        else COLOR_RED
                    )

                    card_embed = DiscordEmbed(
                        title=f"🔹 {symbol}",
                        color=f"{color_code:06x}",
                    )

                    header_info: str = (
                        f"**Action:** {action_text}  │  "
                        f"**Urgency:** `{urgency_text}`  │  "
                        f"**Confidence:** `{conf_text}`"
                    )

                    factor_lines: str = ""
                    if score_info:
                        factor_lines = (
                            f"• **Factor Scores:**\n"
                            f"  - Dip Score: `{score_info.dip_score:.2f}`\n"
                            f"  - Valuation/Cost Score: `{score_info.cost_score:.2f}`\n"
                            f"  - Gap Score: `{score_info.allocation_score:.2f}`\n"
                            f"  - Quant Total: `{score_info.total_score:.3f}`"
                        )

                    card_content: str = (
                        f"{header_info}\n"
                        f"─────────────────────────────────────────\n"
                        f"{factor_lines}\n"
                        f"─────────────────────────────────────────\n"
                        f"_{rec.reasoning}_"
                    )

                    card_embed.set_description(card_content)
                    batch_webhook.add_embed(card_embed)

                batch_webhook.execute()

        logger.success("Successfully sent opportunity_evaluation report to Discord.")
        return True

    except Exception as err:
        logger.error(f"Failed to send Discord notification: {err}")
        return False
