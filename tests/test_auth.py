import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

os.environ["DATABASE_URL"] = "sqlite:///./test.db"

from app import database  # noqa: E402
from app import auth as auth_module  # noqa: E402
from app.auth import require_authenticated_admin, resolve_user_from_request  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User, UserRole  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database() -> None:
    SQLModel.metadata.drop_all(database.engine)
    SQLModel.metadata.create_all(database.engine)
    yield


@pytest.fixture(autouse=True)
def stub_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "get_password_hash", lambda password: f"hashed-{password}")


@pytest.fixture()
def client():
    def override_get_session():
        with Session(database.engine) as session:
            yield session

    app.dependency_overrides[database.get_session] = override_get_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_guest_registration_sets_user_role(client: TestClient) -> None:
    app.dependency_overrides[resolve_user_from_request] = lambda: None

    response = client.post(
        "/auth/register", json={"username": "guest-user", "password": "secret"}
    )

    assert response.status_code == 201
    assert response.json()["role"] == UserRole.USER


def test_registration_rejects_admin_role_attempt(client: TestClient) -> None:
    app.dependency_overrides[resolve_user_from_request] = lambda: None

    response = client.post(
        "/auth/register",
        json={"username": "no-admins", "password": "secret", "role": UserRole.ADMIN},
    )

    assert response.status_code == 400


def test_admin_caller_still_creates_user_role(client: TestClient) -> None:
    admin_user = User(username="admin", role=UserRole.ADMIN, hashed_password="hashed")
    app.dependency_overrides[resolve_user_from_request] = lambda: admin_user

    response = client.post(
        "/auth/register", json={"username": "from-admin", "password": "secret"}
    )

    assert response.status_code == 201
    assert response.json()["role"] == UserRole.USER


def test_admin_creation_available_only_via_admin_endpoint(client: TestClient) -> None:
    admin_user = User(
        username="admin",
        role=UserRole.ADMIN,
        hashed_password="not-used",
    )
    app.dependency_overrides[require_authenticated_admin] = lambda: admin_user

    response = client.post(
        "/auth/admin/users",
        json={"username": "new-admin", "password": "secret", "role": UserRole.ADMIN},
    )

    assert response.status_code == 201
    assert response.json()["role"] == UserRole.ADMIN
