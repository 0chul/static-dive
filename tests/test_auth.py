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
from app.auth import (
    AuthenticatedUser,
    get_current_user,
    require_authenticated_admin,
    require_registered_user,
    resolve_user_from_request,
)  # noqa: E402
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
        "/auth/register",
        json={"username": "guest-user", "password": "secret", "party_identifier": "GuestUser#1000"},
    )

    assert response.status_code == 201
    assert response.json()["role"] == UserRole.USER


def test_registration_rejects_admin_role_attempt(client: TestClient) -> None:
    app.dependency_overrides[resolve_user_from_request] = lambda: None

    response = client.post(
        "/auth/register",
        json={
            "username": "no-admins",
            "password": "secret",
            "role": UserRole.ADMIN,
            "party_identifier": "NoAdmins#1000",
        },
    )

    assert response.status_code == 400


def test_admin_caller_still_creates_user_role(client: TestClient) -> None:
    admin_user = User(username="admin", role=UserRole.ADMIN, hashed_password="hashed")
    app.dependency_overrides[resolve_user_from_request] = lambda: admin_user

    response = client.post(
        "/auth/register",
        json={"username": "from-admin", "password": "secret", "party_identifier": "Admin#1001"},
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
        json={
            "username": "new-admin",
            "password": "secret",
            "role": UserRole.ADMIN,
            "party_identifier": "NewAdmin#2000",
        },
    )

    assert response.status_code == 201
    assert response.json()["role"] == UserRole.ADMIN


def test_private_party_join_does_not_require_gear_preset(client: TestClient) -> None:
    app.dependency_overrides[get_current_user] = lambda: User(
        id=123,
        username="host-123",
        role="user",
        party_identifier="host-123#main",
    )

    party_response = client.post(
        "/parties",
        json={
            "title": "비공개 파티",
            "visibility": "private",
            "description": "테스트 파티",
            "invite_code": "SECRET-INVITE",
        },
    )

    assert party_response.status_code == 201
    party_data = party_response.json()
    assert party_data["invite_code"] == "SECRET-INVITE"

    join_response = client.post(
        "/parties/join-by-code",
        json={"invite_code": "SECRET-INVITE", "applicant_name": "지원자"},
    )

    assert join_response.status_code == 201
    payload = join_response.json()
    assert payload["party"]["id"] == party_data["id"]
    assert payload["member"]["applicant_name"] == "지원자"
    assert payload["member"]["gear_preset"] is None
