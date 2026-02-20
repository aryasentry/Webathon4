"""
Auth schemas — OAuth state, token status, session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl


class OAuthStateResponse(BaseModel):
    authorization_url: str
    state: str


class CallbackRequest(BaseModel):
    code: str
    state: str


class TokenStatus(BaseModel):
    valid: bool
    scopes: list[str]
    github_login: str
    checked_at: datetime


class UserSession(BaseModel):
    user_id: str
    github_id: int
    login: str
    avatar_url: Optional[str] = None
    email: Optional[str] = None
    token_valid: bool
    connected_at: datetime


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserSession
