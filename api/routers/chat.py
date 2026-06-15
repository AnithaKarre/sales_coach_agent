"""
Phase 5 — Chat APIs
POST /api/v1/chat            → Ask SalesCoach (via Orchestrator → Chat Agent)
GET  /api/v1/chat/history    → Chat history for current user
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from api.database import get_db
from api.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


# ── POST /chat ────────────────────────────────────────────────
@router.post("")
async def ask_salescoach(
    req: ChatRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """
    Ask SalesCoach — routes through the Orchestrator Agent.
    Flow: API → Orchestrator Agent → Chat Agent → search_data tool → LLM → Answer
    """

    try:
        uid = user["user_id"]
        role = user["role"]

        # Build message with user context header
        message = f"user_id={uid}\nuser_role={role}\n{req.message}"

        # Route through orchestrator
        orchestrator = request.app.state.orchestrator_agent
        result = None
        try:
            async for response in orchestrator.invoke(messages=message):
                result = response
        except Exception as e:
            print(f"Orchestrator failed ({e}). Falling back to chat_agent directly.")
            chat_agent = request.app.state.chat_agent
            async for response in chat_agent.invoke(messages=message):
                result = response

        answer = str(result.content) if result else ""

        # Check router plugin for routing metadata
        router_plugin = request.app.state.orchestrator_builder.router_plugin
        routing_info = {}
        if router_plugin and router_plugin.last_result:
            routing_info = router_plugin.last_result
            router_plugin.clear()

        # Save to chat history
        try:
            cur = conn.cursor()
            if req.session_id:
                # Append to existing session
                cur.execute(
                    """
                    UPDATE chat_sessions
                    SET messages = messages || %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s::uuid AND user_id = %s::uuid
                    RETURNING id
                    """,
                    (
                        json.dumps([
                            {"role": "user", "content": req.message},
                            {"role": "assistant", "content": answer},
                        ]),
                        req.session_id,
                        uid,
                    ),
                )
                session = cur.fetchone()
                if not session:
                    # Session not found, create new
                    req.session_id = None
            
            if not req.session_id:
                # Create new session
                title = req.message[:100]
                cur.execute(
                    """
                    INSERT INTO chat_sessions (user_id, title, messages)
                    VALUES (%s::uuid, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        uid,
                        title,
                        json.dumps([
                            {"role": "user", "content": req.message},
                            {"role": "assistant", "content": answer},
                        ]),
                    ),
                )
                session = cur.fetchone()
                req.session_id = str(session["id"])

            conn.commit()
        except Exception as e:
            print("DB Error in chat history:", e)
            pass  # Chat history save failure should not block the response

        return {
            "answer": routing_info.get("answer", answer),
            "intent": routing_info.get("intent", "chat"),
            "session_id": req.session_id,
        }
    except Exception as outer_e:
        import traceback
        trace = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Server error: {str(outer_e)}\n\nTraceback: {trace}")


# ── GET /chat/history ────────────────────────────────────────
@router.get("/history")
async def chat_history(
    limit: int = 20,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """Returns the chat session history for the current user."""
    cur = conn.cursor()
    safe_limit = max(1, min(limit, 100))

    cur.execute(
        """
        SELECT id, title, messages, created_at, updated_at
        FROM chat_sessions
        WHERE user_id = %s::uuid
        ORDER BY updated_at DESC
        LIMIT %s
        """,
        (user["user_id"], safe_limit),
    )
    rows = cur.fetchall()

    return [
        {
            "session_id": str(row["id"]),
            "title": row["title"],
            "messages": row["messages"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]
