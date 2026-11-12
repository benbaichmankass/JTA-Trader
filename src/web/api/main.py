"""FastAPI app entrypoint for the dashboard backend.

Serves REST endpoints consumed by the Svelte SPA
(benbaichmankass/ict-trader-dashboard, streamlit_app.py).
"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.web.api import auth as auth_module
from src.web.api.routers import accounts as accounts_router
from src.web.api.routers import alerts as alerts_router
from src.web.api.routers import wake_toggles as wake_toggles_router
from src.web.api.routers import allocator as allocator_router
from src.web.api.routers import brackets_history as brackets_history_router
from src.web.api.routers import performance_categories as performance_categories_router
from src.web.api.routers import attribution as attribution_router
from src.web.api.routers import auth as auth_router
from src.web.api.routers import auth_google as auth_google_router
from src.web.api.routers import backtests as backtests_router
from src.web.api.routers import bot_config as bot_config_router
from src.web.api.routers import candles as candles_router
from src.web.api.routers import dashboard as dashboard_router
from src.web.api.routers import db_explorer as db_explorer_router
from src.web.api.routers import devices as devices_router
from src.web.api.routers import diag as diag_router
from src.web.api.routers import research_runs as research_runs_router
from src.web.api.routers import exit_interval as exit_interval_router
from src.web.api.routers import exit_ladder as exit_ladder_router
from src.web.api.routers import exposure as exposure_router
from src.web.api.routers import feature_impact as feature_impact_router
from src.web.api.routers import fc_geometry as fc_geometry_router
from src.web.api.routers import gpu_spend as gpu_spend_router
from src.web.api.routers import health_snapshots as health_snapshots_router
from src.web.api.routers import insights as insights_router
from src.web.api.routers import learning as learning_router
from src.web.api.routers import liquidity as liquidity_router
from src.web.api.routers import market_ws as market_ws_router
from src.web.api.routers import news as news_router
from src.web.api.routers import notifications as notifications_router
from src.web.api.routers import order_packages as order_packages_router
from src.web.api.routers import pairs as pairs_router
from src.web.api.routers import performance as performance_router
from src.web.api.routers import pnl as pnl_router
from src.web.api.routers import pnl_broker_truth as pnl_broker_truth_router
from src.web.api.routers import pnl_exchange as pnl_exchange_router
from src.web.api.routers import pnl_history as pnl_history_router
from src.web.api.routers import prop as prop_router
from src.web.api.routers import reports as reports_router
from src.web.api.routers import research_catalog as research_catalog_router
from src.web.api.routers import catalog_features as catalog_features_router
from src.web.api.routers import roadmap as roadmap_router
from src.web.api.routers import runtime_config as runtime_config_router
from src.web.api.routers import shadow as shadow_router
from src.web.api.routers import status as status_router
from src.web.api.routers import strategies as strategies_router
from src.web.api.routers import strategy_review as strategy_review_router
from src.web.api.routers import strategy_tune as strategy_tune_router
from src.web.api.routers import trade_scores as trade_scores_router
from src.web.api.routers import trades_closed as trades_closed_router
from src.web.api.routers import training_center as training_center_router
from src.web.api.routers import work as work_router
from src.web.api.routers import work_ledger as work_ledger_router
from src.web.api.routers import work_topics as work_topics_router
from src.web.api.routers import work_items as work_items_router
from src.web.api.routers import live_review_direct as live_review_direct_router
from src.web.api.routers import dd_switch as dd_switch_router

# UI-UPGRADE-1-AUTH: the whole-site gate is an APP-LEVEL dependency (so it covers
# every router and WS /ws/market) that is a no-op until SITE_AUTH_ENFORCE is set.
app = FastAPI(
    title="JTA Trader — Dashboard API",
    version="0.2.0",
    dependencies=[Depends(auth_module.require_site_session)],
)

_dashboard_origin = os.environ.get("DASHBOARD_ORIGIN", "")
_origins = ["http://localhost:5173", "http://localhost:3000"]
if _dashboard_origin:
    _origins.append(_dashboard_origin)
# The Svelte SPA (ict-trader-dashboard/webapp) is served from GitHub Pages and
# calls this API browser-direct, so CORS IS load-bearing for it. ⚠️ Since
# 2026-09-01 the SPA is the ONLY live consumer (Streamlit + Android retired,
# BL-20260901-RETIRE-ANDROID-AND-STREAMLIT-FROM-THE-LIVE-FEED), so a CORS
# mistake here now breaks the entire consumer set — there is no longer a
# server-side Streamlit hop to stay green behind it. Allow the Pages origin (origin is host-only; the
# /ict-trader-dashboard/ path is not part of it). Additional origins (a future
# custom domain, a Pages preview) can be supplied via WEBAPP_ORIGINS (CSV).
_origins.append("https://benbaichmankass.github.io")
_webapp_origins = os.environ.get("WEBAPP_ORIGINS", "")
if _webapp_origins:
    _origins.extend(o.strip() for o in _webapp_origins.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(status_router.router)
app.include_router(pnl_router.router)
app.include_router(pnl_history_router.router)
app.include_router(auth_router.router)
app.include_router(auth_google_router.router)
app.include_router(dashboard_router.router)
app.include_router(bot_config_router.router)
app.include_router(accounts_router.router)
app.include_router(db_explorer_router.router)
app.include_router(liquidity_router.router)
app.include_router(trades_closed_router.router)
app.include_router(order_packages_router.router)
app.include_router(candles_router.router)
app.include_router(performance_router.router)
app.include_router(backtests_router.router)
app.include_router(pnl_exchange_router.router)
app.include_router(pnl_broker_truth_router.router)
app.include_router(diag_router.router)
app.include_router(research_runs_router.router)
app.include_router(shadow_router.router)
app.include_router(health_snapshots_router.router)
app.include_router(trade_scores_router.router)
app.include_router(strategies_router.router)
app.include_router(strategy_review_router.router)
app.include_router(strategy_tune_router.router)
app.include_router(training_center_router.router)
app.include_router(attribution_router.router)
app.include_router(devices_router.router)
app.include_router(insights_router.router)
app.include_router(gpu_spend_router.router)
app.include_router(news_router.router)
app.include_router(notifications_router.router)
app.include_router(alerts_router.router)
app.include_router(wake_toggles_router.router)
app.include_router(exit_ladder_router.router)
app.include_router(fc_geometry_router.router)
app.include_router(allocator_router.router)
app.include_router(exit_interval_router.router)
app.include_router(exposure_router.router)
app.include_router(feature_impact_router.router)
app.include_router(pairs_router.router)
app.include_router(prop_router.router)
app.include_router(brackets_history_router.router)
app.include_router(performance_categories_router.router)
app.include_router(reports_router.router)
app.include_router(roadmap_router.router)
app.include_router(research_catalog_router.router)
app.include_router(catalog_features_router.router)
app.include_router(runtime_config_router.router)
app.include_router(learning_router.router)
app.include_router(market_ws_router.router)
app.include_router(work_router.router)
app.include_router(work_ledger_router.router)
app.include_router(work_topics_router.router)
app.include_router(work_items_router.router)
app.include_router(live_review_direct_router.router)
app.include_router(dd_switch_router.router)


@app.get("/api/health", tags=["health"])
def health() -> dict:
    return {"ok": True}
