from datetime import date
from typing import Annotated, Literal, Optional

import re

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from .utils import Email, Password, UTCDateTime

Role = Literal["admin", "mitarbeiter", "benutzer"]
LeaveKind = Literal["vacation", "sick", "special", "wish"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class TenantRegister(BaseModel):
    company: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    email: Email
    password: Password


class LoginIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str
    new_password: Password


class ResetRequest(BaseModel):
    email: Email


class ResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: Password


def _check_work_days(v: str) -> str:
    v = "".join(sorted(set(v)))
    if not v or any(c not in "1234567" for c in v):
        raise ValueError("Arbeitstage: Ziffern 1 (Montag) bis 7 (Sonntag), mindestens ein Tag")
    return v


WorkDays = Annotated[str, AfterValidator(_check_work_days)]


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    is_locked: bool
    hourly_rate: Optional[float]
    vacation_days: int
    weekly_hours: Optional[float] = None
    is_minor: bool = False
    is_minijob: bool = False
    minijob_limit: Optional[float] = None
    work_days: str
    department_ids: list[int]
    version: int


class MeOut(UserOut):
    permissions: list[str]


# ---------- Benutzer ----------
class UserCreate(BaseModel):
    email: Email
    name: str = Field(min_length=1, max_length=120)
    password: Password
    role: Role = "benutzer"
    hourly_rate: Optional[float] = Field(default=None, ge=0, le=10000)
    vacation_days: int = Field(default=30, ge=0, le=365)
    work_days: WorkDays = "12345"
    weekly_hours: Optional[float] = Field(default=None, gt=0, le=60)
    is_minor: bool = False
    is_minijob: bool = False
    minijob_limit: Optional[float] = Field(default=None, gt=0, le=5000)
    rate_valid_from: Optional[date] = None
    ignore_warnings: bool = False
    department_ids: list[int] = []


class UserUpdate(BaseModel):
    version: int
    email: Optional[Email] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    hourly_rate: Optional[float] = Field(default=None, ge=0, le=10000)
    vacation_days: Optional[int] = Field(default=None, ge=0, le=365)
    work_days: Optional[WorkDays] = None
    weekly_hours: Optional[float] = Field(default=None, gt=0, le=60)
    is_minor: Optional[bool] = None
    is_minijob: Optional[bool] = None
    minijob_limit: Optional[float] = Field(default=None, gt=0, le=5000)
    rate_valid_from: Optional[date] = None
    ignore_warnings: bool = False
    department_ids: Optional[list[int]] = None


class SetPassword(BaseModel):
    password: Password


class RolePermissionsIn(BaseModel):
    permissions: list[str]


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class DepartmentOut(ORM):
    id: int
    name: str


# ---------- Schichten ----------
class ShiftCreate(BaseModel):
    department_id: int
    user_id: Optional[int] = None
    start: UTCDateTime
    end: UTCDateTime
    note: str = Field(default="", max_length=500)
    claim_requires_approval: bool = True
    break_minutes: int = Field(default=0, ge=0, le=240)
    ignore_warnings: bool = False

    @model_validator(mode="after")
    def _check(self):
        if self.end <= self.start:
            raise ValueError("Das Schichtende muss nach dem Beginn liegen")
        if (self.end - self.start).total_seconds() > 24 * 3600:
            raise ValueError("Eine Schicht darf höchstens 24 Stunden dauern")
        return self


class ShiftUpdate(BaseModel):
    version: int
    department_id: Optional[int] = None
    user_id: Optional[int] = None
    start: Optional[UTCDateTime] = None
    end: Optional[UTCDateTime] = None
    note: Optional[str] = Field(default=None, max_length=500)
    claim_requires_approval: Optional[bool] = None
    break_minutes: Optional[int] = Field(default=None, ge=0, le=240)
    ignore_warnings: bool = False


class ShiftOut(BaseModel):
    id: int
    department_id: int
    user_id: Optional[int]
    user_name: Optional[str]
    start: UTCDateTime
    end: UTCDateTime
    note: str
    published: bool
    claim_requires_approval: bool
    break_minutes: int
    pending_claims: int
    version: int


class PublishIn(BaseModel):
    start: UTCDateTime
    end: UTCDateTime
    department_id: Optional[int] = None


class CopyWeekIn(BaseModel):
    source_start: date
    target_start: date
    department_id: Optional[int] = None
    include_assignments: bool = True


class ClaimDecision(BaseModel):
    approve: bool


class ClaimOut(BaseModel):
    id: int
    shift_id: int
    user_id: int
    user_name: str
    status: str


class SwapCreate(BaseModel):
    shift_id: int
    to_user_id: Optional[int] = None


class SwapDecision(BaseModel):
    approve: bool


class SwapOut(BaseModel):
    id: int
    shift_id: int
    department_id: int
    shift_start: UTCDateTime
    shift_end: UTCDateTime
    from_user_id: int
    from_user_name: str
    to_user_id: Optional[int]
    to_user_name: Optional[str]
    status: str


# ---------- Urlaub ----------
class LeaveCreate(BaseModel):
    start_date: date
    end_date: date
    kind: LeaveKind = "vacation"
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _check(self):
        if self.end_date < self.start_date:
            raise ValueError("Das Enddatum darf nicht vor dem Startdatum liegen")
        if (self.end_date - self.start_date).days > 120:
            raise ValueError("Ein Urlaubsantrag darf höchstens 120 Tage umfassen")
        return self


class LeaveDecision(BaseModel):
    approve: bool
    comment: str = Field(default="", max_length=500)


class LeaveOut(BaseModel):
    id: int
    user_id: int
    user_name: str
    start_date: date
    end_date: date
    days: int
    kind: str
    note: str
    status: str
    decision_comment: str


class LeaveBalance(BaseModel):
    user_id: int
    year: int
    entitlement: int
    used: int
    pending: int
    remaining: int


# ---------- Zeiterfassung ----------
class ClockIn(BaseModel):
    shift_id: Optional[int] = None
    consent_location: bool = False
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)


class TimeEntryUpdate(BaseModel):
    clock_in: Optional[UTCDateTime] = None
    clock_out: Optional[UTCDateTime] = None
    note: Optional[str] = Field(default=None, max_length=500)
    approved: Optional[bool] = None


class TimeEntryOut(BaseModel):
    id: int
    user_id: int
    user_name: str
    shift_id: Optional[int]
    clock_in: UTCDateTime
    clock_out: Optional[UTCDateTime]
    minutes: Optional[int]
    approved: bool
    note: str


# ---------- Sonstiges ----------
class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MessageOut(BaseModel):
    id: int
    user_id: int
    user_name: str
    text: str
    created_at: UTCDateTime


class SettingsIn(BaseModel):
    values: dict[str, str]


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    p256dh: str = Field(max_length=255)
    auth: str = Field(max_length=255)


class AbsenceOut(BaseModel):
    user_id: int
    user_name: str
    start_date: date
    end_date: date
    kind: str   # für Kollegen ohne Genehmigungsrecht immer "absent" (Datenschutz)


# ---------- Schichtvorlagen ----------
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    department_id: Optional[int] = None
    start_time: str
    end_time: str
    break_minutes: int = Field(default=0, ge=0, le=240)
    note: str = Field(default="", max_length=500)

    @field_validator("start_time", "end_time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("Uhrzeit im Format HH:MM angeben")
        return v


class TemplateOut(ORM):
    id: int
    name: str
    department_id: Optional[int]
    start_time: str
    end_time: str
    break_minutes: int
    note: str


# ---------- Dokumente ----------
class DocumentOut(BaseModel):
    id: int
    user_id: Optional[int]
    user_name: Optional[str]
    category: str
    title: str
    filename: str
    size: int
    created_at: UTCDateTime


class CompanyOut(BaseModel):
    company_name: str
    privacy_contact: str


class AvailabilityIn(BaseModel):
    """weekday = wöchentlich wiederkehrend; on_date = nur dieser eine Tag (weekday wird daraus abgeleitet)."""
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    on_date: Optional[date] = None
    start_time: str = "00:00"
    end_time: str = "23:59"
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _check(self):
        for v in (self.start_time, self.end_time):
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
                raise ValueError("Uhrzeit im Format HH:MM angeben")
        if self.end_time <= self.start_time:
            raise ValueError("Das Ende muss nach dem Beginn liegen")
        if self.on_date is not None:
            self.weekday = self.on_date.weekday()
        elif self.weekday is None:
            raise ValueError("Wochentag oder Datum angeben")
        return self


class AvailabilityListIn(BaseModel):
    items: list[AvailabilityIn] = Field(max_length=50)


class AvailabilityOut(AvailabilityIn):
    id: int
    user_id: int
    weekday: int


class WageOut(ORM):
    id: int
    hourly_rate: float
    valid_from: date
