"""
Phase 3 — Merchant APIs
GET /api/v1/merchants/prioritized                   → Prioritized list of merchants
GET /api/v1/merchants/{merchant_id}/detail          → Merchant detail (SQL)
GET /api/v1/merchants/{merchant_id}/history         → Merchant visit history
"""

from fastapi import APIRouter, Depends, HTTPException
from api.database import get_db
from api.dependencies import get_current_user, require_role

router = APIRouter(prefix="/api/v1/merchants", tags=["Merchants"])


# ── Helpers ───────────────────────────────────────────────────
def _scope_clause(role: str, user_id: str):
    """Returns (sql_fragment, params) for RBAC scoping against 'm' alias."""
    if role == "Admin":
        return "TRUE", []
    if role == "Manager":
        return (
            "m.assigned_dsp_id IN "
            "(SELECT id FROM users WHERE manager_id = %s::uuid OR id = %s::uuid)",
            [user_id, user_id],
        )
    return "m.assigned_dsp_id = %s::uuid", [user_id]


async def _invoke_insight_agent(app_state, merchant_name: str, mode: str, user_id: str, user_role: str) -> str:
    """Invoke the Merchant Insight Agent for score/recommendation/brief."""
    agent = app_state.insight_agent
    message = f"user_id={user_id}\nuser_role={user_role}\nmode={mode}\nmerchant: {merchant_name}"
    result = None
    async for response in agent.invoke(messages=message):
        result = response
    return str(result.content) if result else ""


# ── GET /merchants/prioritized ────────────────────────────────
@router.get("/prioritized")
async def prioritized_merchants(
    limit: int = 20,
    user: dict = Depends(require_role("DSP", "Manager", "Admin")),
    conn=Depends(get_db),
):
    """
    Returns the precomputed prioritized merchant list from daily_scores
    + recommendations. Pure SQL — NOT AI.
    Scoped by role: DSP sees own merchants, Manager sees team, Admin sees all.
    """
    cur = conn.cursor()

    role = user["role"]
    uid = user["user_id"]
    safe_limit = max(1, min(limit, 100))

    if role == "Admin":
        scope_sql = "TRUE"
        scope_params = []
    elif role == "Manager":
        scope_sql = (
            "m.assigned_dsp_id IN "
            "(SELECT id FROM users WHERE manager_id = %s::uuid OR id = %s::uuid)"
        )
        scope_params = [uid, uid]
    else:
        scope_sql = "m.assigned_dsp_id = %s::uuid"
        scope_params = [uid]

    cur.execute(
        f"""
        SELECT
            m.id        AS merchant_id,
            m.merchant_name AS name,
            m.tier,
            m.region,
            m.area,
            ds.priority_score AS score,
            ds.rank,
            r.recommended_action AS recommendation,
            r.status AS recommendation_status
        FROM merchants m
        JOIN (
            SELECT DISTINCT ON (merchant_id) merchant_id, priority_score, rank
            FROM daily_scores
            ORDER BY merchant_id, score_date DESC
        ) ds ON ds.merchant_id = m.id
        LEFT JOIN LATERAL (
            SELECT recommended_action, status
            FROM recommendations
            WHERE merchant_id = m.id
            ORDER BY recommendation_date DESC, confidence_score DESC
            LIMIT 1
        ) r ON TRUE
        WHERE m.is_active = TRUE AND {scope_sql}
        ORDER BY ds.rank ASC
        LIMIT %s
        """,
        [*scope_params, safe_limit],
    )
    rows = cur.fetchall()
    result = []
    for row in rows:
        result.append({
            "merchant_id": str(row["merchant_id"]),
            "name": row["name"],
            "tier": row["tier"],
            "region": row["region"],
            "area": row["area"],
            "score": float(row["score"]) if row["score"] else None,
            "rank": row["rank"],
            "recommendation": row["recommendation"],
            "recommendation_status": row["recommendation_status"],
        })
    return result


# ── GET /merchants/{merchant_id}/detail ───────────────────────
@router.get("/{merchant_id}/detail")
async def merchant_detail(
    merchant_id: str,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """
    Full merchant detail: profile + signals.
    Pure SQL — no AI.
    """
    cur = conn.cursor()
    scope_sql, scope_params = _scope_clause(user["role"], user["user_id"])

    # Profile
    cur.execute(
        f"""
        SELECT m.id, m.merchant_name, m.region, m.area, m.tier, m.category,
               m.contact_number, m.address, m.latitude, m.longitude,
               m.onboarding_date, m.is_active, u.full_name AS assigned_dsp
        FROM merchants m
        LEFT JOIN users u ON u.id = m.assigned_dsp_id
        WHERE m.id = %s::uuid AND {scope_sql}
        """,
        [merchant_id, *scope_params],
    )
    merchant = cur.fetchone()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found or access denied")

    # Signals (today)
    cur.execute(
        """
        SELECT transaction_volume, transaction_trend, days_since_visit,
               complaint_count, campaign_status, wallet_balance, active_products
        FROM merchant_signals
        WHERE merchant_id = %s::uuid AND signal_date = CURRENT_DATE
        """,
        (merchant_id,),
    )
    signals = cur.fetchone() or {}

    return {
        "merchant_profile": {
            "merchant_id": str(merchant["id"]),
            "merchant_name": merchant["merchant_name"],
            "region": merchant["region"],
            "area": merchant["area"],
            "tier": merchant["tier"],
            "category": merchant["category"],
            "contact_number": merchant["contact_number"],
            "address": merchant["address"],
            "latitude": float(merchant["latitude"]) if merchant["latitude"] else None,
            "longitude": float(merchant["longitude"]) if merchant["longitude"] else None,
            "onboarding_date": str(merchant["onboarding_date"]) if merchant["onboarding_date"] else None,
            "is_active": merchant["is_active"],
            "assigned_dsp": merchant["assigned_dsp"],
        },
        "signals": {
            "transaction_volume": signals.get("transaction_volume"),
            "transaction_trend": float(signals["transaction_trend"]) if signals.get("transaction_trend") else None,
            "days_since_visit": signals.get("days_since_visit"),
            "complaint_count": signals.get("complaint_count"),
            "campaign_status": signals.get("campaign_status"),
            "wallet_balance": float(signals["wallet_balance"]) if signals.get("wallet_balance") else None,
            "active_products": signals.get("active_products"),
        }
    }


# ── GET /merchants/{merchant_id}/history ──────────────────────
@router.get("/{merchant_id}/history")
async def merchant_history(
    merchant_id: str,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """
    Visit history for the merchant.
    """
    cur = conn.cursor()
    # verify access first
    scope_sql, scope_params = _scope_clause(user["role"], user["user_id"])
    cur.execute(
        f"SELECT 1 FROM merchants m WHERE m.id = %s::uuid AND {scope_sql}",
        [merchant_id, *scope_params],
    )
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Merchant not found or access denied")

    # Visit history
    cur.execute(
        """
        SELECT v.visit_date, v.visit_notes, v.outcome, v.duration_mins,
               u.full_name AS visited_by
        FROM visit_history v
        JOIN users u ON u.id = v.dsp_id
        WHERE v.merchant_id = %s::uuid
        ORDER BY v.visit_date DESC
        """,
        (merchant_id,),
    )
    visits = cur.fetchall()

    return [
        {
            "visit_date": str(v["visit_date"]),
            "visit_notes": v["visit_notes"],
            "outcome": v["outcome"],
            "duration_mins": v["duration_mins"],
            "visited_by": v["visited_by"],
        }
        for v in visits
    ]
