import re
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, PlainSerializer


def utcnow() -> datetime:
    """Alle Zeiten werden als naive UTC-Werte gespeichert."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(v):
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            v = datetime.fromisoformat(s)
        except ValueError:
            raise ValueError("Ungültiges Datum/Zeit-Format (ISO 8601 erwartet)")
    if isinstance(v, datetime) and v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


# Eingabe: ISO-String mit/ohne Zeitzone -> naive UTC. Ausgabe: ISO-String mit "Z".
UTCDateTime = Annotated[
    datetime,
    BeforeValidator(to_utc_naive),
    PlainSerializer(lambda d: d.isoformat() + "Z", return_type=str, when_used="json"),
]

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def _norm_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 255 or not _EMAIL_RE.match(v):
        raise ValueError("Ungültige E-Mail-Adresse")
    return v


Email = Annotated[str, AfterValidator(_norm_email)]


def _check_password(v: str) -> str:
    if len(v) < 10:
        raise ValueError("Das Passwort muss mindestens 10 Zeichen lang sein")
    if len(v) > 200:
        raise ValueError("Das Passwort ist zu lang")
    if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
        raise ValueError("Das Passwort muss Buchstaben und Ziffern enthalten")
    return v


Password = Annotated[str, AfterValidator(_check_password)]


def parse_work_days(work_days: str) -> set[int]:
    """'12345' -> {0,1,2,3,4} (Wochentage: 1 = Montag ... 7 = Sonntag)."""
    return {int(c) - 1 for c in (work_days or "12345") if c in "1234567"}


def workdays(a: date, b: date, work_days: str = "12345") -> int:
    """Arbeitstage der Person (Standard Mo-Fr) ohne gesetzliche Feiertage (NRW)."""
    from .holidays import is_holiday
    wd = parse_work_days(work_days)
    days = (a + timedelta(days=i) for i in range((b - a).days + 1))
    return sum(1 for d in days if d.weekday() in wd and not is_holiday(d))


def local_tz():
    """Zeitzone des Betriebs (für Verfügbarkeiten/Ruhezeiten). Fällt ohne tzdata auf feste MEZ zurück."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Berlin")
    except Exception:  # pragma: no cover
        return timezone(timedelta(hours=1))


def to_local(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc).astimezone(local_tz())


def csv_safe(value) -> str:
    """Schutz vor CSV-Injection in Excel."""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s
