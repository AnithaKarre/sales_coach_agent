"""
Phase 4 — Recommendation Action APIs
PATCH /api/v1/recommendations/{id}/status
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.database import get_db
from api.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/recommendations", tags=["Recommendations"])

VALID_STATUSES = ("New", "In Progress", "Done", "Deferred")

# Map frontend-friendly names to DB values
STATUS_MAP = {
    "NEW": "New",
    "IN_PROGRESS": "In Progress",
    "DONE": "Done",
    "DEFERRED": "Deferred",
    # Also accept the DB format directly
    "New": "New",
    "In Progress": "In Progress",
    "Done": "Done",
    "Deferred": "Deferred",
}


class StatusUpdateRequest(BaseModel):
    status: str


# ── PATCH /recommendations/{id}/status ────────────────────────
@router.patch("/{recommendation_id}/status")
async def update_recommendation_status(
    recommendation_id: str,
    req: StatusUpdateRequest,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """
    Update a recommendation's status.
    Only the assigned DSP or Admin can update.
    Valid statuses: NEW, IN_PROGRESS, DONE, DEFERRED.
    """
    db_status = STATUS_MAP.get(req.status)
    if not db_status:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {list(STATUS_MAP.keys())}",
        )

    cur = conn.cursor()
    uid = user["user_id"]
    role = user["role"]

    # Build RBAC scope
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
        UPDATE recommendations r
        SET status = %s,
            status_updated_at = NOW(),
            status_updated_by = %s::uuid
        FROM merchants m
        WHERE r.id = %s::uuid
          AND r.merchant_id = m.id
          AND {scope_sql}
        RETURNING r.id, r.status, r.status_updated_at
        """,
        [db_status, uid, recommendation_id, *scope_params],
    )
    updated = cur.fetchone()

    if not updated:
        conn.rollback()
        raise HTTPException(status_code=404, detail="Recommendation not found or access denied")

    conn.commit()

    # Audit log
    try:
        cur.execute(
            """
            INSERT INTO audit_logs (user_id, action, resource, resource_id, details)
            VALUES (%s::uuid, %s, %s, %s::uuid, %s::jsonb)
            """,
            (
                uid,
                "UPDATE_ACTION_STATUS",
                "recommendation",
                recommendation_id,
                f'{{"new_status": "{db_status}"}}',
            ),
        )
        conn.commit()
    except Exception:
        pass  # Audit failure should not block the response

    return {
        "recommendation_id": str(updated["id"]),
        "status": updated["status"],
        "updated_at": str(updated["status_updated_at"]),
        "message": "Status updated successfully",
    }
