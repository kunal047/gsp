"""Authentication: password login -> signed JWT, and identity introspection."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import auth, models
from ..db import get_db
from ..rbac import Principal, principal

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: str
    role: str
    scope: str | None = None
    full_name: str | None = None


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = (
        db.query(models.User)
        .filter(models.User.username == body.username.strip().lower())
        .first()
    )
    if not user or not user.active or not auth.verify_password(body.password, user.password_hash):
        # Uniform error so valid usernames aren't enumerable.
        raise HTTPException(status_code=401, detail="invalid username or password")
    token = auth.issue_token(
        sub=user.username, role=user.role, scope=user.scope, name=user.full_name
    )
    return TokenOut(
        access_token=token, user=user.username, role=user.role,
        scope=user.scope, full_name=user.full_name,
    )


@router.get("/me", response_model=TokenOut)
def me(p: Principal = Depends(principal), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == p.user).first()
    return TokenOut(
        access_token="", user=p.user, role=p.role, scope=p.scope,
        full_name=user.full_name if user else None,
    )
