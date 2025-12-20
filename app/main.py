import logging
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import create_db_and_tables, engine, get_session
from app.models import (
    ChatMessage,
    ChatMessageCreate,
    ChatMessageRead,
    MemberState,
    Party,
    PartyCreate,
    PartyDetail,
    PartyMember,
    PartyMemberCreate,
    PartyMemberRead,
    PartyMemberStateUpdate,
    PartyJoinByCode,
    PartyJoinResponse,
    PartySlot,
    PartySlotCreate,
    PartySlotRead,
    PartyVisibility,
)
from app.services import calculate_open_slot_count, update_open_slot_count, verify_host_permission
from app.utils import generate_invite_code

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Albion Party Planner", version="0.1.0")


class PartyWebSocketManager:
    def __init__(self) -> None:
        self.active_connections: dict[int, set[WebSocket]] = {}

    async def connect(self, party_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.setdefault(party_id, set()).add(websocket)

    def disconnect(self, party_id: int, websocket: WebSocket) -> None:
        if party_id in self.active_connections:
            self.active_connections[party_id].discard(websocket)
            if not self.active_connections[party_id]:
                self.active_connections.pop(party_id, None)

    async def broadcast(self, party_id: int, message: dict) -> None:
        for connection in list(self.active_connections.get(party_id, set())):
            try:
                await connection.send_json(message)
            except RuntimeError:
                self.disconnect(party_id, connection)


manager = PartyWebSocketManager()


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


@app.get("/config.js", include_in_schema=False, response_class=FileResponse)
def serve_config_js() -> Response:
    config_path = STATIC_DIR / "config.js"
    if config_path.exists():
        return FileResponse(config_path, media_type="application/javascript")
    return JSONResponse({"status": "ok"})


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


def _count_confirmed_members(
    session: Session, party_id: int, exclude_member_id: int | None = None
) -> int:
    statement = select(func.count()).where(
        PartyMember.party_id == party_id,
        PartyMember.state.in_([MemberState.ACCEPTED, MemberState.LOCKED]),
    )
    if exclude_member_id is not None:
        statement = statement.where(PartyMember.id != exclude_member_id)
    return session.exec(statement).one()


def _assert_host_permission(party: Party, host_name: str) -> None:
    if party.host_name != host_name:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="파티장만 멤버를 관리할 수 있습니다.")


def _count_slot_confirmed_members(
    session: Session, slot_id: int, exclude_member_id: int | None = None
) -> int:
    statement = select(func.count()).where(
        PartyMember.slot_id == slot_id,
        PartyMember.state.in_([MemberState.ACCEPTED, MemberState.LOCKED]),
    )
    if exclude_member_id is not None:
        statement = statement.where(PartyMember.id != exclude_member_id)
    return session.exec(statement).one()


def _ensure_capacity_constraints(
    session: Session,
    party: Party,
    target_slot: PartySlot | None,
    member: PartyMember,
    target_state: str,
) -> None:
    if target_state not in {MemberState.ACCEPTED, MemberState.LOCKED}:
        return

    confirmed = _count_confirmed_members(
        session, party.id, exclude_member_id=member.id
    )
    if party.capacity and confirmed >= party.capacity:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="파티 정원이 가득 찼습니다.")

    if target_slot:
        slot_limit = target_slot.ip_target or party.capacity
        if slot_limit:
            occupied = _count_slot_confirmed_members(
                session, target_slot.id, exclude_member_id=member.id
            )
            if occupied >= slot_limit:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="해당 슬롯 정원이 가득 찼습니다.")


def move_member_to_slot(
    party_id: int,
    member_id: int,
    target_slot_id: int,
    session: Session,
    *,
    commit: bool = True,
    target_state: str | None = None,
    party: Party | None = None,
    member: PartyMember | None = None,
) -> PartyMember:
    party = party or _get_party_or_404(session, party_id)
    member = member or session.get(PartyMember, member_id)

    if member is None or member.party_id != party.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="파티원을 찾을 수 없습니다.")

    target_slot = _get_slot_or_404(session, party.id, target_slot_id)

    if member.slot_id == target_slot.id:
        return member

    if member.state in {MemberState.LOCKED, MemberState.REJECTED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="현재 상태에서는 슬롯을 이동할 수 없습니다.")

    _ensure_capacity_constraints(
        session,
        party,
        target_slot,
        member,
        target_state or member.state,
    )

    member.slot_id = target_slot.id
    session.add(member)
    if commit:
        session.commit()
        session.refresh(member)
    return member
def _require_active_member(session: Session, party_id: int, member_id: int) -> PartyMember:
    _get_party_or_404(session, party_id)
    member = session.get(PartyMember, member_id)
    if member is None or member.party_id != party_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="파티원만 채팅할 수 있습니다.")
    if member.state == MemberState.REJECTED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="채팅이 차단된 파티원입니다.")
    return member


def _serialize_chat_message(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "party_id": message.party_id,
        "member_id": message.member_id,
        "author_name": message.author_name,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }


def _create_chat_message(
    session: Session, party_id: int, member: PartyMember, content: str, author_name: str | None
) -> ChatMessage:
    if not content or not content.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="메시지 내용은 비워둘 수 없습니다.")

    message = ChatMessage(
        party_id=party_id,
        member_id=member.id,
        author_name=author_name or member.applicant_name,
        content=content.strip(),
    )
    session.add(message)
    session.commit()
    session.refresh(message)
    return message


@app.post("/parties", response_model=PartyDetail, status_code=status.HTTP_201_CREATED, tags=["parties"])
def create_party(payload: PartyCreate, session: Session = Depends(get_session)) -> PartyDetail:
    invite_code = payload.invite_code
    if payload.visibility == PartyVisibility.PRIVATE and not invite_code:
        invite_code = generate_invite_code()

    party = Party(**payload.dict(exclude={"invite_code"}), invite_code=invite_code)
    session.add(party)
    session.commit()
    session.refresh(party)
    update_open_slot_count(session, party)
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
def create_slot(
    party_id: int,
    payload: PartySlotCreate,
    session: Session = Depends(get_session),
    host_id: str = Query(..., description="파티장 인증자 ID"),
) -> PartySlotRead:
    party = verify_host_permission(session, party_id, host_id)
    open_slots = calculate_open_slot_count(session, party)
    if open_slots is not None and open_slots <= 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="파티 정원을 초과할 수 없습니다.")

    slot = PartySlot(**payload.dict(), party_id=party_id)
    session.add(slot)
    session.commit()
    session.refresh(slot)
    update_open_slot_count(session, party)
    return slot


@app.post(
    "/parties/join-by-code",
    response_model=PartyJoinResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["members"],
)
def join_party_by_code(payload: PartyJoinByCode, session: Session = Depends(get_session)) -> PartyJoinResponse:
    party = session.exec(
        select(Party).where(
            Party.visibility == PartyVisibility.PRIVATE,
            Party.invite_code == payload.invite_code,
        )
    ).first()
    if party is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="초대 코드에 해당하는 비공개 파티를 찾을 수 없습니다."
        )

    slot_id = payload.slot_id
    if slot_id is not None:
        _get_slot_or_404(session, party.id, slot_id)

    member = PartyMember(
        party_id=party.id,
        slot_id=slot_id,
        applicant_name=payload.applicant_name,
        gear_preset=payload.gear_preset,
        state=MemberState.APPLIED,
    )
    session.add(member)
    session.commit()
    session.refresh(member)

    slots = session.exec(select(PartySlot).where(PartySlot.party_id == party.id)).all()
    members = session.exec(select(PartyMember).where(PartyMember.party_id == party.id)).all()
    party_detail = PartyDetail.from_orm(party).copy(update={"slots": slots, "members": members})

    return PartyJoinResponse(party=party_detail, member=member)


@app.post(
    "/parties/{party_id}/apply",
    response_model=PartyMemberRead,
    status_code=status.HTTP_201_CREATED,
    tags=["members"],
)
def apply_to_party(party_id: int, payload: PartyMemberCreate, session: Session = Depends(get_session)) -> PartyMemberRead:
    party = _get_party_or_404(session, party_id)
    if party.visibility == PartyVisibility.PRIVATE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비공개 파티는 /parties/join-by-code 엔드포인트를 통해서만 신청할 수 있습니다.",
        )

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
    host_id: str = Query(..., description="파티장 인증자 ID"),
) -> PartyMemberRead:
    party = _get_party_or_404(session, party_id)
    verify_host_permission(session, party_id, host_id)
    member = session.get(PartyMember, member_id)
    if member is None or member.party_id != party_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="파티원을 찾을 수 없습니다.")

    target_slot = session.get(PartySlot, member.slot_id) if member.slot_id else None
    if payload.slot_id is not None and payload.slot_id != member.slot_id:
        member = move_member_to_slot(
            party_id,
            member_id,
            payload.slot_id,
            session,
            commit=False,
            target_state=payload.state,
            party=party,
            member=member,
        )
        target_slot = session.get(PartySlot, payload.slot_id)

    _ensure_capacity_constraints(session, party, target_slot, member, payload.state)

    member.state = payload.state
    session.add(member)
    session.commit()
    session.refresh(member)
    return member


@app.delete(
    "/parties/{party_id}/members/{member_id}",
    response_model=PartyMemberRead,
    tags=["members"],
)
def remove_member(
    party_id: int,
    member_id: int,
    host_name: str = Query(..., description="파티장 이름 확인"),
    session: Session = Depends(get_session),
) -> PartyMemberRead:
    party = _get_party_or_404(session, party_id)
    _assert_host_permission(party, host_name)

    member = session.get(PartyMember, member_id)
    if member is None or member.party_id != party_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="파티원을 찾을 수 없습니다.")

    member.state = MemberState.KICKED
    member.slot_id = None
    session.add(member)
    session.commit()
    session.refresh(member)

    logger.info("Member %s was kicked from party %s by host %s", member.id, party_id, host_name)
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


@app.post(
    "/parties/{party_id}/chat",
    response_model=ChatMessageRead,
    status_code=status.HTTP_201_CREATED,
    tags=["chat"],
)
async def post_chat_message(
    party_id: int, payload: ChatMessageCreate, session: Session = Depends(get_session)
) -> ChatMessage:
    member = _require_active_member(session, party_id, payload.member_id)
    message = _create_chat_message(
        session=session,
        party_id=party_id,
        member=member,
        content=payload.content,
        author_name=payload.author_name,
    )
    await manager.broadcast(party_id, _serialize_chat_message(message))
    return message


@app.get("/parties/{party_id}/chat", response_model=list[ChatMessageRead], tags=["chat"])
def get_chat_history(
    party_id: int,
    member_id: int = Query(..., description="조회 요청을 하는 파티원 ID"),
    limit: int = Query(50, gt=0, le=200, description="가져올 최대 메시지 수"),
    session: Session = Depends(get_session),
) -> list[ChatMessageRead]:
    _require_active_member(session, party_id, member_id)
    statement = (
        select(ChatMessage)
        .where(ChatMessage.party_id == party_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    messages = session.exec(statement).all()
    return list(reversed(messages))


@app.websocket("/ws/parties/{party_id}")
async def chat_websocket(websocket: WebSocket, party_id: int) -> None:
    member_id_param = websocket.query_params.get("member_id")
    if member_id_param is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="member_id is required")
        return

    try:
        member_id = int(member_id_param)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid member_id")
        return

    with Session(engine) as ws_session:
        try:
            member = _require_active_member(ws_session, party_id, member_id)
        except HTTPException as exc:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=exc.detail)
            return

    await manager.connect(party_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            with Session(engine) as ws_session:
                member = _require_active_member(ws_session, party_id, member_id)
                message = _create_chat_message(
                    session=ws_session,
                    party_id=party_id,
                    member=member,
                    content=data,
                    author_name=None,
                )
                await manager.broadcast(party_id, _serialize_chat_message(message))
    except WebSocketDisconnect:
        manager.disconnect(party_id, websocket)
    except HTTPException as exc:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=exc.detail)
        manager.disconnect(party_id, websocket)
