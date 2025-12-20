from datetime import datetime
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel


class PartyVisibility(str):
    PUBLIC = "public"
    PRIVATE = "private"


class PartyStatus(str):
    OPEN = "open"
    CLOSED = "closed"


class MemberState(str):
    APPLIED = "applied"
    ACCEPTED = "accepted"
    LOCKED = "locked"
    REJECTED = "rejected"
    KICKED = "kicked"


class PartyBase(SQLModel):
    title: str
    description: Optional[str] = None
    visibility: str = Field(default=PartyVisibility.PUBLIC)
    schedule: Optional[str] = None
    capacity: Optional[int] = Field(default=None, ge=1)
    open_slot_count: Optional[int] = Field(default=None, ge=0)
    host_id: str
    voice_channel_link: Optional[str] = None
    status: str = Field(default=PartyStatus.OPEN)
    host_name: str


class Party(PartyBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    invite_code: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    slots: list["PartySlot"] = Relationship(back_populates="party")
    members: list["PartyMember"] = Relationship(back_populates="party")


class PartyCreate(PartyBase):
    visibility: str = Field(default=PartyVisibility.PUBLIC, regex="^(public|private)$")
    invite_code: Optional[str] = None


class PartyRead(PartyBase):
    id: int
    invite_code: Optional[str]
    created_at: datetime


class SlotBase(SQLModel):
    role: str
    ip_target: Optional[int] = Field(default=None, ge=0)
    preset: Optional[dict] = Field(default=None, sa_column=Column(JSON))


class PartySlot(SlotBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    party_id: int = Field(foreign_key="party.id")

    party: Optional[Party] = Relationship(back_populates="slots")
    members: list["PartyMember"] = Relationship(back_populates="slot")


class PartySlotCreate(SlotBase):
    pass


class PartySlotRead(SlotBase):
    id: int
    party_id: int


class MemberBase(SQLModel):
    applicant_name: str
    gear_preset: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    state: str = Field(default=MemberState.APPLIED)


class PartyMember(MemberBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    party_id: int = Field(foreign_key="party.id")
    slot_id: Optional[int] = Field(default=None, foreign_key="partyslot.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    party: Optional[Party] = Relationship(back_populates="members")
    slot: Optional[PartySlot] = Relationship(back_populates="members")


class PartyMemberCreate(SQLModel):
    applicant_name: str
    gear_preset: Optional[dict] = None
    slot_id: Optional[int] = None
    invite_code: Optional[str] = None


class PartyMemberStateUpdate(SQLModel):
    state: str = Field(regex="^(applied|accepted|locked|rejected|kicked)$")
    slot_id: Optional[int] = None


class PartyMemberRead(MemberBase):
    id: int
    party_id: int
    slot_id: Optional[int]
    created_at: datetime


class PartyDetail(PartyRead):
    slots: list[PartySlotRead] = Field(default_factory=list)
    members: list[PartyMemberRead] = Field(default_factory=list)


class PartyJoinByCode(SQLModel):
    invite_code: str
    party_id: Optional[int] = None
    applicant_name: str
    gear_preset: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    slot_id: Optional[int] = None


class PartyJoinResponse(SQLModel):
    party: PartyDetail
    member: PartyMemberRead


class ChatMessageBase(SQLModel):
    author_name: str
    content: str


class ChatMessage(ChatMessageBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    party_id: int = Field(foreign_key="party.id")
    member_id: Optional[int] = Field(default=None, foreign_key="partymember.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessageCreate(SQLModel):
    member_id: int
    content: str
    author_name: Optional[str] = None


class ChatMessageRead(ChatMessageBase):
    id: int
    party_id: int
    member_id: Optional[int]
    created_at: datetime
