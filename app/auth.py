from datetime import datetime, timedelta
import random
import os
import random
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlmodel import Field, Session, SQLModel, select

from app.database import engine, get_session
from app.models import Party, User, UserCreate, UserRead, UserRegister, UserRole


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "asdf1234"
ADMIN_GAME_ID = "admin#0000"


class AuthenticatedUser(BaseModel):
    user_id: str | None
    username: str | None
    role: str
    game_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_authenticated_user(
    request: Request,
    x_user_id: str | None = Header(default=None, convert_underscores=False),
    x_user_name: str | None = Header(default=None, convert_underscores=False),
    x_user_role: str | None = Header(default=None, convert_underscores=False),
    x_game_id: str | None = Header(default=None, convert_underscores=False),
) -> AuthenticatedUser:
    """Simple authentication stub reading user info from headers.

    Role defaults to "guest" when not provided, and any unknown role will be
    coerced to guest.
    """

    resolved_user = getattr(request.state, "user", None)
    if resolved_user is not None:
        return AuthenticatedUser(
            user_id=str(resolved_user.id),
            username=resolved_user.username,
            role=resolved_user.role,
            game_id=resolved_user.game_id,
        )

    normalized_role = (x_user_role or "guest").lower()
    if normalized_role not in {"admin", "user", "guest"}:
        normalized_role = "guest"

    return AuthenticatedUser(
        user_id=x_user_id,
        username=x_user_name,
        role=normalized_role,
        game_id=x_game_id,
    )


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


def generate_party_identifier_suggestion(identifier: str) -> str:
    base = (identifier or "player").split("#", 1)[0] or "player"
    random_tag = f"{random.randint(0, 9999):04d}"
    return f"{base}#{random_tag}"


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


def require_host_or_admin(
    party_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Party:
    party = session.get(Party, party_id)
    if party is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="파티를 찾을 수 없습니다.")

    if user.role == UserRole.ADMIN:
        return party

    if party.host_id != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="파티장만 수행할 수 있는 작업입니다."
        )

    return party


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(
    user_in: UserRegister,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(resolve_user_from_request),
) -> User:
    request_payload = await request.json()
    requested_role = request_payload.get("role")
    if isinstance(requested_role, str) and requested_role.lower() != UserRole.USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role cannot be set during registration",
        )

    existing_user = session.exec(select(User).where(User.username == user_in.username)).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "이미 사용 중인 사용자명입니다. 다른 아이디를 입력해주세요.",
                "field": "username",
            },
        )

    existing_identifier = session.exec(select(User).where(User.game_id == user_in.game_id)).first()
    if existing_identifier:
        suggestion = generate_party_identifier_suggestion(user_in.game_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "이미 사용 중인 게임 ID입니다. 제안된 ID를 확인해주세요.",
                "field": "party_identifier",
                "suggested_party_identifier": suggestion,
            },
        )

    if user_in.username == ADMIN_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="기본 관리자 계정은 등록할 수 없습니다.",
        )

    role = UserRole.USER

    user = User(
        username=user_in.username,
        role=role,
        hashed_password=get_password_hash(user_in.password),
        game_id=user_in.game_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def require_authenticated_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다")
    return current_user


@router.post("/admin/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user_with_role(
    user_in: UserCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_authenticated_admin),
) -> User:
    if user_in.username == ADMIN_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="기본 관리자 계정은 생성할 수 없습니다.",
        )
    existing_user = session.exec(select(User).where(User.username == user_in.username)).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")

    user = User(
        username=user_in.username,
        role=user_in.role,
        hashed_password=get_password_hash(user_in.password),
        game_id=user_in.game_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


class UserRoleUpdate(SQLModel):
    role: str = Field(regex="^(admin|user|guest)$")


@router.patch("/admin/users/{username}/role", response_model=UserRead)
def update_user_role(
    username: str,
    role_update: UserRoleUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_authenticated_admin),
) -> User:
    if username == ADMIN_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="기본 관리자 계정은 수정할 수 없습니다.",
        )
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.role = role_update.role
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
        data={
            "sub": user.username,
            "role": user.role,
            "game_id": user.game_id,
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")


def ensure_default_admin(session: Session | None = None) -> None:
    owns_session = session is None
    if session is None:
        session = Session(engine)

    admin_user = session.exec(select(User).where(User.username == ADMIN_USERNAME)).first()
    if admin_user is None:
        hashed_password = get_password_hash(ADMIN_PASSWORD)
        admin_user = User(
            username=ADMIN_USERNAME,
            role=UserRole.ADMIN,
            hashed_password=hashed_password,
            game_id=ADMIN_GAME_ID,
        )
        session.add(admin_user)
        session.commit()
        if owns_session:
            session.close()
        return

    updated = False
    if admin_user.role != UserRole.ADMIN:
        admin_user.role = UserRole.ADMIN
        updated = True

    password_mismatch = False
    try:
        password_mismatch = not verify_password(ADMIN_PASSWORD, admin_user.hashed_password)
    except Exception:
        hashed_password = get_password_hash(ADMIN_PASSWORD)
        password_mismatch = admin_user.hashed_password != hashed_password
    else:
        hashed_password = None

    if password_mismatch:
        hashed_password = hashed_password or get_password_hash(ADMIN_PASSWORD)
        admin_user.hashed_password = hashed_password
        updated = True

    if admin_user.game_id != ADMIN_GAME_ID:
        admin_user.game_id = ADMIN_GAME_ID
        updated = True

    if updated:
        session.add(admin_user)
        session.commit()

    if owns_session:
        session.close()


