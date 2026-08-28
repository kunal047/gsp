"""RBAC + audit.

The acting principal is derived from a **verified signed token** (Authorization:
Bearer <JWT>), not from caller-supplied headers - so a client cannot self-assign
a role or district. The token is minted by /api/auth/login after a password
check and signed with a server-side secret; a forged role fails signature
verification. Scoping + action gating + audit attribution then key off the
verified claims.

Roles:
  state_admin      - full access, all districts, may act
  district_officer - scoped to one district (token scope), may act
  viewer           - read-only, all districts

A legacy header path remains available ONLY when NETRA_DEV_AUTH=1 (off by
default) for local development; in normal operation headers are ignored.
"""
import os
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import auth, models
from .db import get_db

ROLES = {"state_admin", "district_officer", "viewer"}
CAN_ACT = {"state_admin", "district_officer"}
DEV_AUTH = os.getenv("NETRA_DEV_AUTH") == "1"


@dataclass
class Principal:
    user: str
    role: str
    scope: str | None  # district for district_officer


def principal(
    authorization: str = Header(default=""),
    x_user: str = Header(default=""),
    x_role: str = Header(default=""),
    x_scope: str = Header(default=""),
) -> Principal:
    if authorization.lower().startswith("bearer "):
        claims = auth.verify_token(authorization[7:].strip())
        if claims is None:
            raise HTTPException(status_code=401, detail="invalid or expired token")
        role = claims.get("role") if claims.get("role") in ROLES else "viewer"
        return Principal(user=claims.get("sub") or "unknown", role=role,
                         scope=claims.get("scope"))
    if DEV_AUTH:
        role = x_role if x_role in ROLES else "viewer"
        return Principal(user=x_user or "demo", role=role, scope=x_scope or None)
    raise HTTPException(status_code=401, detail="authentication required")


def require_actor(p: Principal = Depends(principal)) -> Principal:
    if p.role not in CAN_ACT:
        raise HTTPException(
            status_code=403,
            detail=f"role '{p.role}' is read-only and cannot perform this action",
        )
    return p


def audit(db: Session, p: Principal, action: str, detail: str = ""):
    db.add(
        models.AuditLog(
            user=p.user, role=p.role, action=action, detail=detail
        )
    )
    db.commit()


def audit_dep(action: str):
    """Factory: a dependency that logs an audited action for this request."""

    def _dep(
        p: Principal = Depends(principal), db: Session = Depends(get_db)
    ) -> Principal:
        audit(db, p, action)
        return p

    return _dep
