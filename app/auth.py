from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.database import get_session
from app.models import Party
from sqlmodel import Session


class AuthenticatedUser(BaseModel):
    user_id: str | None
    username: str | None
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_authenticated_user(
    x_user_id: str | None = Header(default=None, convert_underscores=False),
    x_user_name: str | None = Header(default=None, convert_underscores=False),
    x_user_role: str | None = Header(default=None, convert_underscores=False),
) -> AuthenticatedUser:
    """Simple authentication stub reading user info from headers.

    Role defaults to "guest" when not provided, and any unknown role will be
    coerced to guest.
    """

    normalized_role = (x_user_role or "guest").lower()
    if normalized_role not in {"admin", "user", "guest"}:
        normalized_role = "guest"

    return AuthenticatedUser(user_id=x_user_id, username=x_user_name, role=normalized_role)


def require_role(*roles: str):
    def dependency(user: AuthenticatedUser = Depends(get_authenticated_user)) -> AuthenticatedUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="권한이 없습니다."
            )
        return user

    return dependency


def require_registered_user(
    user: AuthenticatedUser = Depends(require_role("admin", "user")),
) -> AuthenticatedUser:
    return user


def require_admin(user: AuthenticatedUser = Depends(require_role("admin"))) -> AuthenticatedUser:
    return user


def require_host_or_admin(
    party_id: int,
    session: Session = Depends(get_session),
    user: AuthenticatedUser = Depends(get_authenticated_user),
) -> Party:
    party = session.get(Party, party_id)
    if party is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="파티를 찾을 수 없습니다.")

    if user.is_admin:
        return party

    if party.host_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="파티장만 수행할 수 있는 작업입니다."
        )

    return party
