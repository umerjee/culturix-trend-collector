from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, DateTime

from app.db import Base


class RunpodOrphanKill(Base):
    """Audit record of a pod app.scheduler.run_runpod_orphan_pod_reaper
    auto-terminated for running longer than ORPHAN_POD_MAX_AGE_HOURS.
    Exists so an auto-kill is actually visible somewhere (GET /admin/
    runpod-orphan-kills) instead of only a log line nobody's watching —
    added 2026-09-16 after a manually-created evaluation pod ran
    unterminated for ~5.5 hours and real money was billed for it with no
    independent check catching it."""
    __tablename__ = "runpod_orphan_kills"

    id = Column(Integer, primary_key=True, index=True)
    pod_id = Column(String(64), nullable=False)
    pod_name = Column(String(200), nullable=True)
    gpu_display_name = Column(String(100), nullable=True)
    cost_per_hr = Column(Float, nullable=True)
    age_hours = Column(Float, nullable=False)
    estimated_cost = Column(Float, nullable=True)
    killed_at = Column(DateTime, default=datetime.utcnow, index=True)
