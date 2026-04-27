"""Authentication helpers for the paper trading web UI.

Password hashing uses bcrypt directly. Sessions are stored in auth_sessions
(StateStore). The FastAPI dependency require_token validates Bearer tokens.
"""

import secrets

import bcrypt

from straddle.paper_trading.state import StateStore


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_session(store: StateStore) -> str:
    """Issue a 256-bit URL-safe token and persist it."""
    token = secrets.token_urlsafe(32)
    store.create_session(token)
    return token


def destroy_session(store: StateStore, token: str) -> None:
    store.destroy_session(token)


def require_token(store: StateStore):
    """Return a FastAPI dependency that validates Bearer tokens against the DB.

    Usage in an endpoint:
        @app.get("/signals")
        async def list_signals(token=Depends(require_token(store))):
            ...
    """
    from fastapi import HTTPException, Security
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    security = HTTPBearer()

    async def _check(credentials: HTTPAuthorizationCredentials = Security(security)):
        if not store.validate_session(credentials.credentials):
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return credentials.credentials

    return _check
