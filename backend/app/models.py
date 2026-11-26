from datetime import date, datetime
from typing import Optional

from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer,
                        String, Table, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .utils import utcnow

user_departments = Table(
    "user_departments", Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("department_id", ForeignKey("departments.id"), primary_key=True),
)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("tenant_id", "role", "permission"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    permission: Mapped[str] = mapped_column(String(50))


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="benutzer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    reset_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reset_expires: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    hourly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vacation_days: Mapped[int] = mapped_column(Integer, default=30)
    phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    job_title: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hire_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    contract_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    hr_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # interne Notiz der Personalverwaltung
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_minijob: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    minijob_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # max. Verdienst/Monat; leer = Firmenvorgabe
    weekly_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    work_days: Mapped[str] = mapped_column(String(7), default="12345", server_default="12345")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    departments: Mapped[list["Department"]] = relationship(secondary=user_departments, lazy="selectin")
    __mapper_args__ = {"version_id_col": version}

    @property
    def department_ids(self) -> list[int]:
        return sorted(d.id for d in self.departments)

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > utcnow())


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (Index("ix_shifts_tenant_start", "tenant_id", "start"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    note: Mapped[str] = mapped_column(String(500), default="")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    claim_requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    __mapper_args__ = {"version_id_col": version}


class ShiftClaim(Base):
    __tablename__ = "shift_claims"
    __table_args__ = (UniqueConstraint("shift_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SwapRequest(Base):
    __tablename__ = "swap_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    to_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|accepted|approved|rejected|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TimeEntry(Base):
    __tablename__ = "time_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    shift_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    clock_in: Mapped[datetime] = mapped_column(DateTime)
    clock_out: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(500), default="")
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(500), default="")
    kind: Mapped[str] = mapped_column(String(20), default="vacation")  # vacation|sick|special|wish
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected|cancelled
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_comment: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))


class ShiftTemplate(Base):
    """Schichtvorlage: Uhrzeiten in Ortszeit (HH:MM); angewendet wird sie im Client auf einen Tag."""
    __tablename__ = "shift_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(60))
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(500), default="")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)  # None = Firmendokument
    category: Mapped[str] = mapped_column(String(20), default="sonstiges")
    title: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    stored_name: Mapped[str] = mapped_column(String(64), unique=True)
    uploaded_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Availability(Base):
    """Wiederkehrende Nichtverfügbarkeit einer Person (z. B. „montags nie vor 10 Uhr“)."""
    __tablename__ = "availabilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)          # 0 = Montag ... 6 = Sonntag
    start_time: Mapped[str] = mapped_column(String(5), default="00:00")  # HH:MM
    end_time: Mapped[str] = mapped_column(String(5), default="23:59")
    note: Mapped[str] = mapped_column(String(200), default="")
    on_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)   # gesetzt = nur dieser eine Tag, sonst wöchentlich
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WageHistory(Base):
    """Stundensatz mit Gültigkeit ab einem Datum (Verlauf; die Auswertung nimmt den am Tag gültigen Satz)."""
    __tablename__ = "wage_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    hourly_rate: Mapped[float] = mapped_column(Float)
    valid_from: Mapped[date] = mapped_column(Date)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaskTemplate(Base):
    """Wiederkehrende Aufgabe/Checkliste. Die Aufgaben entstehen automatisch (siehe services/tasks.py)."""
    __tablename__ = "task_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000), default="")
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True)
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    weekdays: Mapped[str] = mapped_column(String(7), default="01234")      # 0 = Montag … 6 = Sonntag
    due_time: Mapped[str] = mapped_column(String(5), default="18:00")      # Ortszeit
    items: Mapped[str] = mapped_column(Text, default="[]")                 # JSON-Liste von Texten
    require_comment: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_generated: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("template_id", "due_date"), Index("ix_tasks_tenant_status", "tenant_id", "status"))
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000), default="")
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True)
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # Ortsdatum bei wiederkehrenden Aufgaben
    priority: Mapped[int] = mapped_column(Integer, default=1)              # 0 niedrig, 1 normal, 2 hoch
    items: Mapped[str] = mapped_column(Text, default="[]")                 # JSON: [{text, done, by, at}]
    require_comment: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="open")        # open | done
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    completion_comment: Mapped[str] = mapped_column(String(500), default="")
    template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("task_templates.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
