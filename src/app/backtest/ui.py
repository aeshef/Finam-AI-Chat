from __future__ import annotations

import os
from typing import Any, List
import io
import csv

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def store_backtest_result(
    metrics: dict[str, Any],
    equity_curve: List[float],
    times: List[str] | None = None,
    closes: List[float] | None = None,
    trades: list[Any] | None = None,
    opens: List[float] | None = None,
    highs: List[float] | None = None,
    lows: List[float] | None = None,
    volumes: List[float] | None = None,
) -> go.Figure:
    """Persist latest backtest result in session state and return the equity figure."""
    x = times if times is not None else list(range(len(equity_curve)))
    # Two stacked subplots: row1 = Equity, row2 = Candles + Volume
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.5, 0.5], specs=[[{}], [{"secondary_y": True}]])
    # Equity top (single axis)
    fig.add_trace(go.Scatter(x=x, y=equity_curve, name="Equity"), row=1, col=1)
    fig.update_yaxes(title_text="Equity", secondary_y=False, row=1, col=1)
    # Candles + Volume bottom
    if closes is not None and opens is not None and highs is not None and lows is not None:
        px = times if times is not None else list(range(len(closes)))
        fig.add_trace(
            go.Candlestick(x=px, open=opens, high=highs, low=lows, close=closes, name="Price"),
            row=2,
            col=1,
            secondary_y=False,
        )
        if volumes is not None:
            fig.add_trace(
                go.Bar(x=px, y=volumes, name="Volume", marker_color="#aaa", opacity=0.4),
                row=2,
                col=1,
                secondary_y=True,
            )
            fig.update_yaxes(title_text="Volume", secondary_y=True, row=2, col=1)
        fig.update_yaxes(title_text="Price", secondary_y=False, row=2, col=1)
        # mark trades on candles
        if trades and times is not None:
            buy_x = [t.time for t in trades if getattr(t, "action", "").lower() == "buy"]
            buy_y = [t.price for t in trades if getattr(t, "action", "").lower() == "buy"]
            sell_x = [t.time for t in trades if getattr(t, "action", "").lower() == "sell"]
            sell_y = [t.price for t in trades if getattr(t, "action", "").lower() == "sell"]
            if buy_x:
                fig.add_trace(
                    go.Scatter(x=buy_x, y=buy_y, mode="markers", name="B", marker=dict(color="green", symbol="triangle-up", size=10)),
                    row=2,
                    col=1,
                    secondary_y=False,
                )
            if sell_x:
                fig.add_trace(
                    go.Scatter(x=sell_x, y=sell_y, mode="markers", name="S", marker=dict(color="red", symbol="triangle-down", size=10)),
                    row=2,
                    col=1,
                    secondary_y=False,
                )
    # tighten equity axis on row1
    if equity_curve:
        ymin = min(equity_curve)
        ymax = max(equity_curve)
        pad = max(1e-6, (ymax - ymin) * 0.03)
        fig.update_yaxes(range=[ymin - pad, ymax + pad], row=1, col=1)
    fig.update_layout(height=600, margin=dict(l=10, r=10, t=30, b=10))
    st.session_state["_bt_metrics"] = metrics
    st.session_state["_bt_equity_fig"] = fig
    # trades are stored by caller if needed as _bt_trades
    return fig


def render_backtest_export(trades: list[Any] | None = None) -> None:
    """Render export buttons for latest backtest result if present."""
    metrics = st.session_state.get("_bt_metrics")
    fig = st.session_state.get("_bt_equity_fig")
    if not metrics or fig is None:
        return
    st.markdown("### 📦 Экспорт бэктеста")
    c1, c2, c3 = st.columns(3)
    with c1:
        try:
            # to_image requires kaleido
            png_bytes = fig.to_image(format="png")  # type: ignore[attr-defined]
            st.download_button("🖼️ Equity PNG", data=png_bytes, file_name="backtest_equity.png", mime="image/png", key="bt_png")
        except Exception as e:  # pragma: no cover
            st.info("PNG: требуется пакет 'kaleido'")
    with c2:
        try:
            html_str = fig.to_html(full_html=False)  # type: ignore[attr-defined]
            st.download_button("💾 Equity HTML", data=html_str, file_name="backtest_equity.html", mime="text/html", key="bt_html")
        except Exception as e:  # pragma: no cover
            st.error(f"HTML экспорт недоступен: {e}")
    with c3:
        if trades is not None:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=["time", "action", "price", "quantity"])  # type: ignore[arg-type]
            writer.writeheader()
            for t in trades:
                writer.writerow({"time": t.time, "action": t.action, "price": t.price, "quantity": t.quantity})
            st.download_button("📄 Trades CSV", data=buf.getvalue(), file_name="backtest_trades.csv", mime="text/csv", key="bt_csv")


