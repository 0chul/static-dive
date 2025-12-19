from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Party, PartySlot


def verify_host_permission(session: Session, party_id: int, host_id: str) -> Party:
    party = session.get(Party, party_id)
    if party is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="파티를 찾을 수 없습니다.")
    if party.host_id != host_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="파티장만 수정할 수 있습니다.")
    return party


def calculate_open_slot_count(session: Session, party: Party) -> int | None:
    if party.capacity is None:
        return None
    slot_count = session.exec(select(func.count()).where(PartySlot.party_id == party.id)).one()
    return max(party.capacity - slot_count, 0)


def update_open_slot_count(session: Session, party: Party) -> Party:
    party.open_slot_count = calculate_open_slot_count(session, party)
    session.add(party)
    session.commit()
    session.refresh(party)
    return party
