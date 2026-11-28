"""Spaltentyp für verschlüsselte Texte (AES-256-GCM, Schlüssel DOCUMENTS_KEY).

Die Anwendung arbeitet weiter mit Klartext; in der Datenbank (und damit in Datenbank-Dumps,
auf der Festplatte und bei einem Datenbank-Einbruch) steht nur der verschlüsselte Wert.
Nach verschlüsselten Feldern kann nicht gesucht oder sortiert werden.
"""
from sqlalchemy.types import Text, TypeDecorator


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        from .services.crypto import encrypt_field
        return encrypt_field(value)

    def process_result_value(self, value, dialect):
        from .services.crypto import decrypt_field
        return decrypt_field(value)
