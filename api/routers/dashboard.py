"""
Phase 2 — Dashboard APIs

Implements required endpoints:
- GET /api/v1/dashboard/dsp
- GET /api/v1/dashboard/manager
- GET /api/v1/dashboard/admin
"""


from fastapi import APIRouter, Depends, HTTPException
from api.database import get_db
from api.dependencies import get_current_user, require_role

router = APIRouter(prefix="/api/v1", tags=["Dashboard"])


# ── GET /dashboard/dsp ────────────────────────────────────────
@router.get("/dashboard/dsp")
async def dsp_dashboard(
    user: dict = Depends(require_role("DSP")),
    conn=Depends(get_db),
):
    """
    DSP Dashboard summary: total merchants, high-priority count,
    and recommended visits for today. Pure SQL — no AI.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(DISTINCT m.id) AS total_merchants,
            COUNT(DISTINCT CASE
                WHEN ds.priority_score >= 70 THEN m.id
            END) AS high_priority,
            COUNT(DISTINCT CASE
                WHEN r.status IN ('New', 'In Progress') THEN m.id
            END) AS recommended_visits
        FROM merchants m
        LEFT JOIN daily_scores ds
            ON ds.merchant_id = m.id AND ds.score_date = CURRENT_DATE
        LEFT JOIN recommendations r
            ON r.merchant_id = m.id AND r.recommendation_date = CURRENT_DATE
        WHERE m.assigned_dsp_id = %s
          AND m.is_active = TRUE
        """,
        (user["user_id"],),
    )
    row = cur.fetchone()
    return {
        "total_merchants": row["total_merchants"] or 0,
        "high_priority": row["high_priority"] or 0,
        "recommended_visits": row["recommended_visits"] or 0,
    }


# ── GET /dashboard/manager ────────────────────────────────────
@router.get("/dashboard/manager")
async def manager_dashboard(
    user: dict = Depends(require_role("Manager", "Admin")),
    conn=Depends(get_db),
):
    """
    Manager Dashboard summary: stats for all DSPs under this manager.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(DISTINCT m.id) AS total_merchants,
            COUNT(DISTINCT CASE
                WHEN ds.priority_score >= 70 THEN m.id
            END) AS high_priority,
            COUNT(DISTINCT CASE
                WHEN r.status IN ('New', 'In Progress') THEN m.id
            END) AS recommended_visits
        FROM merchants m
        LEFT JOIN daily_scores ds
            ON ds.merchant_id = m.id AND ds.score_date = CURRENT_DATE
        LEFT JOIN recommendations r
            ON r.merchant_id = m.id AND r.recommendation_date = CURRENT_DATE
        WHERE m.assigned_dsp_id IN (
            SELECT id FROM users WHERE manager_id = %s OR id = %s
        ) AND m.is_active = TRUE
        """,
        (user["user_id"], user["user_id"]),
    )
    row = cur.fetchone()
    return {
        "total_merchants": row["total_merchants"] or 0,
        "high_priority": row["high_priority"] or 0,
        "recommended_visits": row["recommended_visits"] or 0,
    }


# ── GET /dashboard/admin ──────────────────────────────────────
@router.get("/dashboard/admin")
async def admin_dashboard(
    user: dict = Depends(require_role("Admin")),
    conn=Depends(get_db),
):
    """
    Admin Dashboard summary: global stats across all merchants.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(DISTINCT m.id) AS total_merchants,
            COUNT(DISTINCT CASE
                WHEN ds.priority_score >= 70 THEN m.id
            END) AS high_priority,
            COUNT(DISTINCT CASE
                WHEN r.status IN ('New', 'In Progress') THEN m.id
            END) AS recommended_visits
        FROM merchants m
        LEFT JOIN daily_scores ds
            ON ds.merchant_id = m.id AND ds.score_date = CURRENT_DATE
        LEFT JOIN recommendations r
            ON r.merchant_id = m.id AND r.recommendation_date = CURRENT_DATE
        WHERE m.is_active = TRUE
        """
    )
    row = cur.fetchone()
    return {
        "total_merchants": row["total_merchants"] or 0,
        "high_priority": row["high_priority"] or 0,
        "recommended_visits": row["recommended_visits"] or 0,
    }
