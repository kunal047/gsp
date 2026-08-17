"""Lightweight RBAC + audit.

The acting principal is carried on each request via X-User / X-Role / X-Scope
headers (set by the front-end role switcher). In deployment these come from the
department SSO / identity provider — the enforcement here (scoping + action
gating + audit attribution) is the same either way.

Roles:
  state_admin      — full access, all districts, may act
  district_officer — scoped to one district (X-Scope), may act
  viewer           — read-only, all districts
"""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import models
from .db import get_db

ROLES = {"state_admin", "district_officer", "viewer"}
CAN_ACT = {"state_admin", "district_officer"}


@dataclass
class Principal:
    user: str
    role: str
    scope: str | None  # district for district_officer


def principal(
    x_user: str = Header(default="demo"),
    x_role: str = Header(default="state_admin"),
    x_scope: str = Header(default=""),
) -> Principal:
    role = x_role if x_role in ROLES else "viewer"
    return Principal(user=x_user or "demo", role=role, scope=x_scope or None)


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
