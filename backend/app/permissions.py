ROLES = ("admin", "mitarbeiter", "benutzer")

ALL_PERMISSIONS = {
    "shifts.view": "Dienstplan ansehen",
    "shifts.manage": "Dienstplan erstellen und bearbeiten",
    "availability.manage": "Verfügbarkeit anderer Personen sehen und pflegen",
    "swap.request": "Schichttausch anfragen und annehmen",
    "leave.request": "Urlaub beantragen",
    "leave.approve": "Urlaub genehmigen",
    "time.clock": "Ein- und Ausstempeln",
    "time.approve": "Arbeitszeiten prüfen und freigeben",
    "users.view": "Benutzerliste ansehen",
    "users.manage": "Benutzer verwalten",
    "roles.manage": "Rollen und Rechte verwalten",
    "reports.view": "Berichte und Lohnvorbereitung",
    "chat.use": "Team-Chat nutzen",
    "documents.view": "Dokumente ansehen (eigene und Firmendokumente)",
    "documents.manage": "Dokumente aller Personen verwalten",
    "settings.manage": "Einstellungen ändern",
    "admin.audit": "Protokolle und Systeminformationen",
    "admin.backup": "Backups verwalten",
}

# "benutzer" = Schichtmitarbeiter, "mitarbeiter" = Planer/Büro, "admin" = alles (fest verdrahtet)
DEFAULT_ROLE_PERMISSIONS = {
    "benutzer": ["shifts.view", "swap.request", "leave.request", "time.clock", "chat.use", "documents.view"],
    "mitarbeiter": [
        "shifts.view", "shifts.manage", "availability.manage", "swap.request", "leave.request", "leave.approve",
        "time.clock", "time.approve", "users.view", "reports.view", "chat.use", "documents.view",
    ],
}
