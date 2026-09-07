from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Date, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY

from app.db import Base


class CalendarEvent(Base):
    """A single upcoming occurrence of a cultural, religious or political
    event — the calendar context content_strategist.py reads to write
    ideas that anticipate what's actually coming up, not just react to
    what's already trending (see app/pipeline/nodes/calendar_context.py).

    Sourced two different ways, tracked via `source`:
      - "api:nager" — national/public holidays, auto-refreshed from Nager.Date
        (free, no key, decent coverage) by app/services/calendar_events.py's
        sync_holidays() — safe to overwrite/re-upsert on every sync.
      - "curated" — religious observances (mostly lunar/lunisolar calendars
        that holiday APIs don't compute correctly) and political events (no
        API exists for these at all) — hand-maintained, see
        app/services/calendar_events.py's CURATED_EVENTS list. Never
        overwritten by the API sync.

    `date` is the actual concrete date of THIS occurrence (2026's Diwali,
    2027's Diwali, etc.), not a recurrence rule — simpler to query ("what's
    in the next 45 days") at the cost of needing fresh rows added/synced
    each year rather than computed on the fly.
    """
    __tablename__ = "calendar_events"
    __table_args__ = (
        # Same (name, date) can't be synced in twice by a repeated API/seed
        # run — upserts key off this rather than accumulating duplicates.
        UniqueConstraint("name", "date", name="uq_calendar_event_name_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    category = Column(String(20), nullable=False, index=True)  # holiday | religious | political
    date = Column(Date, nullable=False, index=True)
    # ISO-2-ish region codes this event is relevant to (same normalize_region()
    # vocabulary the trend collectors use — see app/collectors/region_codes.py),
    # e.g. ["IN"] for Diwali, ["US","GB","CA","AU","FR","DE",...] for a broadly
    # diaspora-relevant religious observance. Empty/null means globally relevant
    # (e.g. a global awareness day) rather than tied to specific countries.
    regions = Column(ARRAY(String(8)), nullable=True)
    description = Column(Text, nullable=True)
    source = Column(String(20), nullable=False)  # api:nager | curated
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
