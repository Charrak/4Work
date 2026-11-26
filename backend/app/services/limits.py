"""Betriebliche Grenzwerte aus den Einstellungen (mit gesetzlichen Standardwerten)."""
from sqlalchemy import select

from ..models import Setting

DEFAULTS = {
    "minimum_wage": 13.90,      # gesetzlicher Mindestlohn 2026 (€/h) – bei Änderung bitte in den Einstellungen anpassen
    "max_daily_hours": 10.0,    # § 3 ArbZG: 8 h, bis 10 h verlängerbar (Ausgleich innerhalb 6 Monaten)
    "max_weekly_hours": 48.0,   # Obergrenze im Durchschnitt (6 Monate); hier als Wochenwarnung
    "surcharge_night_pct": 0.0,     # Zuschläge in % vom Stundensatz; 0 = keine (Tarif/Vertrag eintragen)
    "surcharge_sunday_pct": 0.0,
    "surcharge_holiday_pct": 0.0,
    "minijob_limit": 603.0,     # Minijob-Monatsgrenze 2026 (€); ändert sich mit dem Mindestlohn – bitte prüfen
    "period_start_day": 15.0,   # Abrechnungszeitraum: Starttag im Monat (15 = vom 15. bis 14.; 1 = Kalendermonat)
    "block_clock_over_limit": 0.0,  # 1 = Einstempeln wird bei Überschreitung gesperrt
}


def get_limit(db, tenant_id: int, key: str) -> float:
    row = db.get(Setting, (tenant_id, key))
    try:
        return float(str(row.value).replace(",", ".")) if row and row.value not in (None, "") else DEFAULTS[key]
    except ValueError:
        return DEFAULTS[key]
