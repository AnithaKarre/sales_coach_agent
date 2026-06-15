"""
SalesCoach AI — API Server
==========================
Complete REST API with JWT authentication and role-based access control.

Phase 1: Auth       — /api/v1/auth/*
Phase 2: Dashboard  — /api/v1/dashboard/*, /api/v1/merchants/prioritized
Phase 3: Merchants  — /api/v1/merchants/{id}/*
Phase 4: Actions    — /api/v1/recommendations/{id}/status
Phase 5: Chat       — /api/v1/chat, /api/v1/chat/history
Phase 6: Manager    — /api/v1/manager/*
Phase 7: Admin      — /api/v1/admin/*
Phase 8: Tools      — internal MCP server (agent_plugin_verse/db_plugin/server.py)

Run:
    uvicorn api.main:app --host 0.0.0.0 --port 8080
(Requires the Merchant DB MCP server running on http://localhost:9002/sse)
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
import uvicorn
sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_verse.chat_agent.agent import ChatAgent
from agent_verse.merchant_insight_agent.agent import MerchantInsightAgent
from agent_verse.orchestrator_agent.agent import OrchestratorAgent
from utils.logger import log


# ----------------------------------------------------------------------
# App lifespan — build each agent ONCE and reuse across requests
# ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.debug("Building agents for API server...")

    # Build the two sub-agents first
    app.state.chat_agent = await ChatAgent().get_agent()
    app.state.insight_agent = await MerchantInsightAgent().get_agent()

    # Build the orchestrator with references to the sub-agents
    orchestrator_builder = OrchestratorAgent()
    app.state.orchestrator_agent = await orchestrator_builder.build(
        insight_agent=app.state.insight_agent,
        chat_agent=app.state.chat_agent,
    )
    app.state.orchestrator_builder = orchestrator_builder

    log.debug("All agents ready (Orchestrator + Merchant Insight + Chat).")
    yield
    # nothing to tear down explicitly


app = FastAPI(
    title="SalesCoach AI API",
    description="GCash SalesCoach AI — Multi-Agent Sales Coaching Platform",
    version="2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------
# Register all routers
# ----------------------------------------------------------------------
from api.routers import auth, dashboard, merchants, recommendations, chat, manager, admin

app.include_router(auth.router)           # Phase 1
app.include_router(dashboard.router)      # Phase 2
app.include_router(merchants.router)      # Phase 3
app.include_router(recommendations.router) # Phase 4
app.include_router(chat.router)           # Phase 5
app.include_router(manager.router)        # Phase 6
app.include_router(admin.router)          # Phase 7


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------
@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "agents": ["orchestrator", "merchant_insight", "chat"]}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)