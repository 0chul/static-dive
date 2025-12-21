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
from datetime import datetime, timedelta
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import Session, SQLModel, select

from app.database import engine, get_session
from app.models import User, UserCreate, UserRead

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class Token(SQLModel):
    access_token: str
    token_type: str


class TokenData(SQLModel):
    username: Optional[str] = None
    role: Optional[str] = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_user_from_token(token: str, session: Session) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token_data = TokenData(username=username, role=payload.get("role"))
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    statement = select(User).where(User.username == token_data.username)
    user = session.exec(statement).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)
) -> User:
    return get_user_from_token(token, session)


async def add_user_to_request_state(request: Request, user: User = Depends(get_current_user)) -> User:
    request.state.user = user
    return user


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(user_in: UserCreate, session: Session = Depends(get_session)) -> User:
    existing_user = session.exec(select(User).where(User.username == user_in.username)).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")

    user = User(
        username=user_in.username,
        role=user_in.role,
        hashed_password=get_password_hash(user_in.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)
) -> Token:
    user = session.exec(select(User).where(User.username == form_data.username)).first()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")


async def resolve_user_from_request(request: Request) -> Optional[User]:
    request.state.user = None
    try:
        token = await oauth2_scheme(request)
    except HTTPException:
        return None

    with Session(engine) as session:
        try:
            user = get_user_from_token(token, session)
        except HTTPException:
            return None
    request.state.user = user
    return user
