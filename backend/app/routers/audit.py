from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit")
def list_audit(
    limit: int = Query(60, le=500),
    action: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.AuditLog)
    if action:
        q = q.filter(models.AuditLog.action == action)
    rows = q.order_by(models.AuditLog.id.desc()).limit(limit).all()
    return [
        {
            "id": a.id,
            "user": a.user,
            "role": a.role,
            "action": a.action,
            "detail": a.detail,
            "ts": a.ts,
        }
        for a in rows
    ]
