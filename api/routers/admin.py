"""
Phase 7 — Admin APIs
GET    /api/v1/admin/users             → List users
POST   /api/v1/admin/users             → Create user
PATCH  /api/v1/admin/users/{id}        → Update user
DELETE /api/v1/admin/users/{id}        → Deactivate user
GET    /api/v1/admin/audit-logs        → Query audit logs
PATCH  /api/v1/admin/users/{id}/role   → Reassign role
"""

import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.database import get_db
from api.dependencies import require_role, hash_password

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


# ── Request Models ────────────────────────────────────────────
class CreateUserRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str  # DSP, Manager, Admin
    region: Optional[str] = None
    area: Optional[str] = None
    manager_id: Optional[str] = None


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    region: Optional[str] = None
    area: Optional[str] = None
    manager_id: Optional[str] = None
    is_active: Optional[bool] = None


class RoleUpdateRequest(BaseModel):
    role: str  # DSP, Manager, Admin


# ── GET /admin/users ──────────────────────────────────────────
@router.get("/users")
async def list_users(
    role_filter: Optional[str] = None,
    region: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 100,
    user: dict = Depends(require_role("Admin")),
    conn=Depends(get_db),
):
    """List all users with optional filters. Admin only."""
    cur = conn.cursor()
    conditions = []
    params = []

    if role_filter:
        conditions.append("u.role = %s")
        params.append(role_filter)
    if region:
        conditions.append("u.region = %s")
        params.append(region)
    if is_active is not None:
        conditions.append("u.is_active = %s")
        params.append(is_active)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    safe_limit = max(1, min(limit, 500))

    cur.execute(
        f"""
        SELECT u.id, u.email, u.full_name, u.role, u.region, u.area,
               u.is_active, u.created_at,
               mgr.full_name AS manager_name
        FROM users u
        LEFT JOIN users mgr ON mgr.id = u.manager_id
        {where}
        ORDER BY u.role, u.full_name
        LIMIT %s
        """,
        [*params, safe_limit],
    )
    rows = cur.fetchall()
    return [
        {
            "user_id": str(r["id"]),
            "email": r["email"],
            "full_name": r["full_name"],
            "role": r["role"],
            "region": r["region"],
            "area": r["area"],
            "is_active": r["is_active"],
            "manager_name": r["manager_name"],
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


# ── POST /admin/users ────────────────────────────────────────
@router.post("/users", status_code=201)
async def create_user(
    req: CreateUserRequest,
    user: dict = Depends(require_role("Admin")),
    conn=Depends(get_db),
):
    """Create a new user. Admin only."""
    valid_roles = ("DSP", "Manager", "Admin")
    if req.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of {valid_roles}")

    cur = conn.cursor()

    # Check email uniqueness
    cur.execute("SELECT id FROM users WHERE email = %s", (req.email,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="Email already exists")

    cur.execute(
        """
        INSERT INTO users (email, password_hash, full_name, role, region, area, manager_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id, email, full_name, role
        """,
        (
            req.email,
            hash_password(req.password),
            req.full_name,
            req.role,
            req.region,
            req.area,
            req.manager_id,
        ),
    )
    new_user = cur.fetchone()
    conn.commit()

    # Audit log
    cur.execute(
        """
        INSERT INTO audit_logs (user_id, action, resource, resource_id, details)
        VALUES (%s, 'CREATE_USER', 'user', %s, %s::jsonb)
        """,
        (user["user_id"], str(new_user["id"]), json.dumps({"email": req.email, "role": req.role})),
    )
    conn.commit()

    return {
        "user_id": str(new_user["id"]),
        "email": new_user["email"],
        "full_name": new_user["full_name"],
        "role": new_user["role"],
        "message": "User created successfully",
    }


# ── PATCH /admin/users/{id} ──────────────────────────────────
@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    user: dict = Depends(require_role("Admin")),
    conn=Depends(get_db),
):
    """Update an existing user. Admin only."""
    cur = conn.cursor()

    # Build dynamic SET clause
    fields = []
    params = []
    if req.full_name is not None:
        fields.append("full_name = %s")
        params.append(req.full_name)
    if req.email is not None:
        fields.append("email = %s")
        params.append(req.email)
    if req.region is not None:
        fields.append("region = %s")
        params.append(req.region)
    if req.area is not None:
        fields.append("area = %s")
        params.append(req.area)
    if req.manager_id is not None:
        fields.append("manager_id = %s")
        params.append(req.manager_id)
    if req.is_active is not None:
        fields.append("is_active = %s")
        params.append(req.is_active)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields.append("updated_at = NOW()")
    set_clause = ", ".join(fields)
    params.append(user_id)

    cur.execute(
        f"UPDATE users SET {set_clause} WHERE id = %s RETURNING id, full_name, email, role, is_active",
        params,
    )
    updated = cur.fetchone()
    if not updated:
        conn.rollback()
        raise HTTPException(status_code=404, detail="User not found")

    conn.commit()
    return {
        "user_id": str(updated["id"]),
        "full_name": updated["full_name"],
        "email": updated["email"],
        "role": updated["role"],
        "is_active": updated["is_active"],
        "message": "User updated successfully",
    }


# ── DELETE /admin/users/{id} ─────────────────────────────────
@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    user: dict = Depends(require_role("Admin")),
    conn=Depends(get_db),
):
    """Soft-delete (deactivate) a user. Admin only."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET is_active = FALSE, updated_at = NOW() WHERE id = %s RETURNING id, full_name",
        (user_id,),
    )
    deleted = cur.fetchone()
    if not deleted:
        conn.rollback()
        raise HTTPException(status_code=404, detail="User not found")

    conn.commit()

    # Audit log
    cur.execute(
        """
        INSERT INTO audit_logs (user_id, action, resource, resource_id, details)
        VALUES (%s, 'DEACTIVATE_USER', 'user', %s, %s::jsonb)
        """,
        (user["user_id"], user_id, json.dumps({"deactivated_user": deleted["full_name"]})),
    )
    conn.commit()

    return {"user_id": str(deleted["id"]), "message": f"User '{deleted['full_name']}' deactivated"}


# ── GET /admin/audit-logs ────────────────────────────────────
@router.get("/audit-logs")
async def get_audit_logs(
    action: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(require_role("Admin")),
    conn=Depends(get_db),
):
    """Query audit logs with optional action filter. Admin only."""
    cur = conn.cursor()
    safe_limit = max(1, min(limit, 200))

    if action:
        cur.execute(
            """
            SELECT a.id, a.action, a.resource, a.resource_id, a.details,
                   a.ip_address, a.created_at, u.full_name AS user_name
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.action ILIKE %s
            ORDER BY a.created_at DESC
            LIMIT %s
            """,
            (f"%{action}%", safe_limit),
        )
    else:
        cur.execute(
            """
            SELECT a.id, a.action, a.resource, a.resource_id, a.details,
                   a.ip_address, a.created_at, u.full_name AS user_name
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            ORDER BY a.created_at DESC
            LIMIT %s
            """,
            (safe_limit,),
        )

    rows = cur.fetchall()
    return [
        {
            "id": str(r["id"]),
            "action": r["action"],
            "resource": r["resource"],
            "resource_id": str(r["resource_id"]) if r["resource_id"] else None,
            "details": r["details"],
            "ip_address": str(r["ip_address"]) if r["ip_address"] else None,
            "user_name": r["user_name"],
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


# ── PATCH /admin/users/{id}/role ─────────────────────────────
@router.patch("/users/{user_id}/role")
async def assign_role(
    user_id: str,
    req: RoleUpdateRequest,
    user: dict = Depends(require_role("Admin")),
    conn=Depends(get_db),
):
    """Reassign a user's role. Admin only."""
    valid_roles = ("DSP", "Manager", "Admin")
    if req.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of {valid_roles}")

    cur = conn.cursor()
    cur.execute(
        "SELECT role FROM users WHERE id = %s",
        (user_id,),
    )
    existing = cur.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = existing["role"]
    cur.execute(
        "UPDATE users SET role = %s, updated_at = NOW() WHERE id = %s RETURNING id, full_name, role",
        (req.role, user_id),
    )
    updated = cur.fetchone()
    conn.commit()

    # Audit log
    cur.execute(
        """
        INSERT INTO audit_logs (user_id, action, resource, resource_id, details)
        VALUES (%s, 'ROLE_CHANGE', 'user', %s, %s::jsonb)
        """,
        (
            user["user_id"],
            user_id,
            json.dumps({"old_role": old_role, "new_role": req.role}),
        ),
    )
    conn.commit()

    return {
        "user_id": str(updated["id"]),
        "full_name": updated["full_name"],
        "old_role": old_role,
        "new_role": updated["role"],
        "message": "Role updated successfully",
    }
