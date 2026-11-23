"""Lohnvorbereitung: Stundensatz-Verlauf, Zuschläge (Nacht/Sonntag/Feiertag), Minijob-Monatsgrenze.

Keine Lohnabrechnung im steuerlichen Sinn: Lohnsteuer, Sozialversicherung usw. werden NICHT berechnet.
Das Ergebnis ist eine Brutto-Vorbereitung für Lohnbüro/Steuerberater/Lohnsoftware.

Regeln (bewusst einfach und dokumentiert):
- Nachtzuschlag: Arbeitszeit zwischen 23:00 und 06:00 Uhr (lokale Zeit).
- Sonntag- und Feiertagszuschlag schließen sich aus: es gilt der höhere der beiden Prozentsätze.
- Nachtzuschlag wird zusätzlich gezahlt (Summe).
- Die Pause wird anteilig von allen Abschnitten des Eintrags abgezogen.
"""
from bisect import bisect_right
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import select

from ..holidays import is_holiday
from ..models import WageHistory
from ..utils import to_local

NIGHT_START, NIGHT_END = time(23, 0), time(6, 0)


class RateTable:
    """Stundensatz je Person und Datum aus dem Verlauf; Fallback = aktueller Satz im Benutzer."""

    def __init__(self, db, tenant_id: int, fallback: dict[int, Optional[float]]):
        self.fallback = fallback
        self.dates: dict[int, list[date]] = {}
        self.rates: dict[int, list[float]] = {}
        for w in db.scalars(select(WageHistory).where(WageHistory.tenant_id == tenant_id)
                            .order_by(WageHistory.user_id, WageHistory.valid_from, WageHistory.id)).all():
            self.dates.setdefault(w.user_id, []).append(w.valid_from)
            self.rates.setdefault(w.user_id, []).append(w.hourly_rate)

    def rate(self, user_id: int, d: date) -> float:
        ds = self.dates.get(user_id)
        if ds:
            i = bisect_right(ds, d)
            if i:
                return self.rates[user_id][i - 1]
            return 0.0  # Eintrag beginnt erst später: für frühere Tage ist kein Satz bekannt
        return self.fallback.get(user_id) or 0.0


def segments(start_local: datetime, end_local: datetime):
    """Teilt [start, end) an lokaler Mitternacht, 06:00 und 23:00 in Abschnitte gleicher Art."""
    cur = start_local
    while cur < end_local:
        d = cur.date()
        marks = [datetime.combine(d, NIGHT_END, tzinfo=cur.tzinfo), datetime.combine(d, NIGHT_START, tzinfo=cur.tzinfo),
                 datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=cur.tzinfo)]
        nxt = min([m for m in marks if m > cur] + [end_local])
        nxt = min(nxt, end_local)
        yield cur, nxt
        cur = nxt


def entry_pay(user_id: int, clock_in: datetime, clock_out: datetime, paid_hours: float,
              rates: RateTable, night_pct: float, sunday_pct: float, holiday_pct: float):
    """Gibt (Grundlohn, Zuschläge, Stunden Nacht, Stunden Sonntag, Stunden Feiertag) für einen Eintrag zurück."""
    ls, le = to_local(clock_in), to_local(clock_out)
    gross = max((le - ls).total_seconds() / 3600, 1e-9)
    factor = paid_hours / gross
    base = sur = h_night = h_sun = h_hol = 0.0
    for a, b in segments(ls, le):
        h = (b - a).total_seconds() / 3600 * factor
        rate = rates.rate(user_id, a.date())
        base += h * rate
        night = a.time() >= NIGHT_START or a.time() < NIGHT_END
        pct = 0.0
        if night:
            pct += night_pct
            h_night += h
        day_pct = 0.0
        if is_holiday(a.date()):
            day_pct = holiday_pct
            h_hol += h
        elif a.weekday() == 6:
            day_pct = sunday_pct
            h_sun += h
        if a.weekday() == 6 and is_holiday(a.date()):
            day_pct = max(sunday_pct, holiday_pct)
        pct += day_pct
        sur += h * rate * pct / 100
    return base, sur, h_night, h_sun, h_hol
