from collections.abc import Generator
import os

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import GearPreset, GearPresetVisibility, PartySlot

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_slot_gearpreset_column()
    _migrate_slot_presets()


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""

    with Session(engine) as session:
        yield session


def _ensure_slot_gearpreset_column() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("partyslot")}
    if "gear_preset_id" in columns:
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE partyslot ADD COLUMN gear_preset_id INTEGER"))


def _migrate_slot_presets() -> None:
    with Session(engine) as session:
        legacy_slots = session.exec(
            select(PartySlot).where(
                PartySlot.gear_preset_id.is_(None), PartySlot.preset.is_not(None)
            )
        ).all()

        if not legacy_slots:
            return

        for slot in legacy_slots:
            preset = GearPreset(
                owner_id="system",
                visibility=GearPresetVisibility.MASTER,
                preset=slot.preset or {},
                metadata={"source": "legacy_slot", "party_id": slot.party_id, "slot_id": slot.id},
            )
            session.add(preset)
            session.commit()
            session.refresh(preset)

            slot.gear_preset_id = preset.id
            slot.preset = None
            session.add(slot)

        session.commit()
