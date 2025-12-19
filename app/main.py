from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import create_db_and_tables, get_session
from app.models import (
    MemberState,
    Party,
    PartyCreate,
    PartyDetail,
    PartyMember,
    PartyMemberCreate,
    PartyMemberRead,
    PartyMemberStateUpdate,
    PartySlot,
    PartySlotCreate,
    PartySlotRead,
    PartyVisibility,
)
from app.utils import generate_invite_code

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Albion Party Planner", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()


@app.get("/", include_in_schema=False, response_class=FileResponse)
def serve_index() -> Response:
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"status": "ok"})


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


def _get_party_or_404(session: Session, party_id: int) -> Party:
    party = session.get(Party, party_id)
    if party is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="파티를 찾을 수 없습니다.")
    return party


def _get_slot_or_404(session: Session, party_id: int, slot_id: int) -> PartySlot:
    slot = session.get(PartySlot, slot_id)
    if slot is None or slot.party_id != party_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 파티의 슬롯을 찾을 수 없습니다.")
    return slot


def _count_confirmed_members(session: Session, party_id: int) -> int:
    statement = select(func.count()).where(
        PartyMember.party_id == party_id,
        PartyMember.state.in_([MemberState.ACCEPTED, MemberState.LOCKED]),
    )
    return session.exec(statement).one()


@app.post("/parties", response_model=PartyDetail, status_code=status.HTTP_201_CREATED, tags=["parties"])
def create_party(payload: PartyCreate, session: Session = Depends(get_session)) -> PartyDetail:
    invite_code = payload.invite_code
    if payload.visibility == PartyVisibility.PRIVATE and not invite_code:
        invite_code = generate_invite_code()

    party = Party(**payload.dict(exclude={"invite_code"}), invite_code=invite_code)
    session.add(party)
    session.commit()
    session.refresh(party)
    return PartyDetail.from_orm(party).copy(update={"slots": [], "members": []})


@app.get("/parties", response_model=list[PartyDetail], tags=["parties"])
def list_parties(
    session: Session = Depends(get_session),
    visibility: str | None = Query(default=None, regex="^(public|private)$"),
    role: str | None = Query(default=None, description="필터링할 슬롯 역할"),
    q: str | None = Query(default=None, description="제목 검색어"),
) -> list[PartyDetail]:
    statement = select(Party)
    if visibility:
        statement = statement.where(Party.visibility == visibility)
    if q:
        statement = statement.where(Party.title.ilike(f"%{q}%"))
    parties = session.exec(statement).all()

    results: list[PartyDetail] = []
    for party in parties:
        slots_stmt = select(PartySlot).where(PartySlot.party_id == party.id)
        members_stmt = select(PartyMember).where(PartyMember.party_id == party.id)
        if role:
            slots_stmt = slots_stmt.where(PartySlot.role.ilike(f"%{role}%"))
            members_stmt = members_stmt.where(PartyMember.slot_id.in_(select(PartySlot.id).where(PartySlot.role.ilike(f"%{role}%"))))
        slots = session.exec(slots_stmt).all()
        members = session.exec(members_stmt).all()
        results.append(PartyDetail.from_orm(party).copy(update={"slots": slots, "members": members}))
    return results


@app.get("/parties/{party_id}", response_model=PartyDetail, tags=["parties"])
def read_party(party_id: int, session: Session = Depends(get_session)) -> PartyDetail:
    party = _get_party_or_404(session, party_id)
    slots = session.exec(select(PartySlot).where(PartySlot.party_id == party_id)).all()
    members = session.exec(select(PartyMember).where(PartyMember.party_id == party_id)).all()
    return PartyDetail.from_orm(party).copy(update={"slots": slots, "members": members})


@app.post("/parties/{party_id}/slots", response_model=PartySlotRead, status_code=status.HTTP_201_CREATED, tags=["slots"])
def create_slot(party_id: int, payload: PartySlotCreate, session: Session = Depends(get_session)) -> PartySlotRead:
    _get_party_or_404(session, party_id)
    slot = PartySlot(**payload.dict(), party_id=party_id)
    session.add(slot)
    session.commit()
    session.refresh(slot)
    return slot


@app.post(
    "/parties/{party_id}/apply",
    response_model=PartyMemberRead,
    status_code=status.HTTP_201_CREATED,
    tags=["members"],
)
def apply_to_party(party_id: int, payload: PartyMemberCreate, session: Session = Depends(get_session)) -> PartyMemberRead:
    party = _get_party_or_404(session, party_id)
    if party.visibility == PartyVisibility.PRIVATE and party.invite_code != payload.invite_code:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="유효하지 않은 초대 코드입니다.")

    slot_id = payload.slot_id
    if slot_id is not None:
        _get_slot_or_404(session, party_id, slot_id)

    member = PartyMember(
        party_id=party_id,
        slot_id=slot_id,
        applicant_name=payload.applicant_name,
        gear_preset=payload.gear_preset,
        state=MemberState.APPLIED,
    )
    session.add(member)
    session.commit()
    session.refresh(member)
    return member


@app.post(
    "/parties/{party_id}/members/{member_id}/state",
    response_model=PartyMemberRead,
    tags=["members"],
)
def update_member_state(
    party_id: int,
    member_id: int,
    payload: PartyMemberStateUpdate,
    session: Session = Depends(get_session),
) -> PartyMemberRead:
    _get_party_or_404(session, party_id)
    member = session.get(PartyMember, member_id)
    if member is None or member.party_id != party_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="파티원을 찾을 수 없습니다.")

    if payload.slot_id:
        _get_slot_or_404(session, party_id, payload.slot_id)
        member.slot_id = payload.slot_id

    if payload.state in {MemberState.ACCEPTED, MemberState.LOCKED} and member.state != payload.state:
        confirmed = _count_confirmed_members(session, party_id)
        party = session.get(Party, party_id)
        if party and party.capacity and confirmed >= party.capacity:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="파티 정원이 가득 찼습니다.")

    member.state = payload.state
    session.add(member)
    session.commit()
    session.refresh(member)
    return member


@app.post("/parties/{party_id}/invite-code", response_model=dict, tags=["parties"])
def regenerate_invite_code(party_id: int, session: Session = Depends(get_session)) -> dict:
    party = _get_party_or_404(session, party_id)
    if party.visibility != PartyVisibility.PRIVATE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="공개 파티는 초대 코드가 필요 없습니다.")

    party.invite_code = generate_invite_code()
    session.add(party)
    session.commit()
    session.refresh(party)
    return {"invite_code": party.invite_code}


@app.get("/parties/{party_id}/slots", response_model=list[PartySlotRead], tags=["slots"])
def list_slots(party_id: int, session: Session = Depends(get_session)) -> list[PartySlotRead]:
    _get_party_or_404(session, party_id)
    return session.exec(select(PartySlot).where(PartySlot.party_id == party_id)).all()


@app.get("/parties/{party_id}/members", response_model=list[PartyMemberRead], tags=["members"])
def list_members(party_id: int, session: Session = Depends(get_session)) -> list[PartyMemberRead]:
    _get_party_or_404(session, party_id)
    return session.exec(select(PartyMember).where(PartyMember.party_id == party_id)).all()
