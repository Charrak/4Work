"""Verschlüsselung ruhender Daten (AES-256-GCM).

* Dokumente: jede Datei einzeln mit DOCUMENTS_KEY (32 Byte, URL-sicheres Base64).
* Sensible Textfelder in der Datenbank (Telefon, Personalnotiz, Urlaubs-/Krankmeldungs-Notizen,
  Zeit-Notizen, Chat): ebenfalls mit DOCUMENTS_KEY, gespeichert als "enc1:<Base64>".
* Backups: Datei-Stream in 1-MiB-Blöcken mit einem aus BACKUP_PASSPHRASE per scrypt abgeleiteten Schlüssel;
  der letzte Block ist markiert, damit abgeschnittene Dateien erkannt werden.
Geht der Schlüssel bzw. die Passphrase verloren, sind die Daten NICHT wiederherstellbar.
"""
import base64
import hashlib
import os
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings

DOC_MAGIC = b"DPENC1"
BACKUP_MAGIC = b"DPBK1"
CHUNK = 1 << 20


class CryptoError(Exception):
    pass


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _doc_key() -> bytes | None:
    if not settings.documents_key:
        return None
    try:
        key = base64.urlsafe_b64decode(settings.documents_key.encode())
    except Exception as e:  # noqa: BLE001
        raise CryptoError("DOCUMENTS_KEY ist kein gültiges URL-sicheres Base64") from e
    if len(key) != 32:
        raise CryptoError("DOCUMENTS_KEY muss 32 Byte lang sein (python -m app.cli gen-key)")
    return key


def is_encrypted_doc(blob: bytes) -> bool:
    return blob.startswith(DOC_MAGIC)


def encrypt_doc(data: bytes) -> bytes:
    """Verschlüsselt, wenn ein Schlüssel konfiguriert ist (nur Entwicklung/Test dürfen ohne laufen)."""
    key = _doc_key()
    if key is None:
        return data
    nonce = os.urandom(12)
    return DOC_MAGIC + nonce + AESGCM(key).encrypt(nonce, data, DOC_MAGIC)


def decrypt_doc(blob: bytes) -> bytes:
    """Alte, unverschlüsselte Dateien (vor Einführung der Verschlüsselung) werden unverändert geliefert."""
    if not is_encrypted_doc(blob):
        return blob
    key = _doc_key()
    if key is None:
        raise CryptoError("Das Dokument ist verschlüsselt, aber DOCUMENTS_KEY fehlt")
    nonce, ct = blob[len(DOC_MAGIC):len(DOC_MAGIC) + 12], blob[len(DOC_MAGIC) + 12:]
    try:
        return AESGCM(key).decrypt(nonce, ct, DOC_MAGIC)
    except InvalidTag as e:
        raise CryptoError("Dokument lässt sich nicht entschlüsseln (falscher Schlüssel oder beschädigt)") from e


# ---------- Datenbankfelder ----------
FIELD_PREFIX = "enc1:"
FIELD_AAD = b"DPFLD1"


def is_encrypted_field(value) -> bool:
    return isinstance(value, str) and value.startswith(FIELD_PREFIX)


def encrypt_field(value: str) -> str:
    """Verschlüsselt einen Text. Ohne Schlüssel (nur Entwicklung/Test) bleibt er unverändert."""
    if value is None or value == "" or is_encrypted_field(value):
        return value
    key = _doc_key()
    if key is None:
        return value
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, value.encode("utf-8"), FIELD_AAD)
    return FIELD_PREFIX + base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt_field(value):
    """Ältere, noch unverschlüsselte Werte werden unverändert zurückgegeben."""
    if not is_encrypted_field(value):
        return value
    key = _doc_key()
    if key is None:
        raise CryptoError("Verschlüsseltes Datenbankfeld, aber DOCUMENTS_KEY fehlt")
    raw = base64.urlsafe_b64decode(value[len(FIELD_PREFIX):].encode())
    try:
        return AESGCM(key).decrypt(raw[:12], raw[12:], FIELD_AAD).decode("utf-8")
    except InvalidTag as e:
        raise CryptoError("Datenbankfeld lässt sich nicht entschlüsseln (falscher Schlüssel?)") from e


# ---------- Backups ----------
def _derive(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 15, r=8, p=1, maxmem=128 * 1024 * 1024, dklen=32)


def encrypt_stream(src: BinaryIO, dst: BinaryIO, passphrase: str) -> None:
    if not passphrase:
        raise CryptoError("BACKUP_PASSPHRASE fehlt")
    salt, prefix = os.urandom(16), os.urandom(8)
    header = BACKUP_MAGIC + salt + prefix
    aes = AESGCM(_derive(passphrase, salt))
    dst.write(header)
    buf, counter = src.read(CHUNK), 0
    while True:
        nxt = src.read(CHUNK)
        last = not nxt
        ct = aes.encrypt(prefix + counter.to_bytes(4, "big"), buf, header + (b"\x01" if last else b"\x00"))
        dst.write(len(ct).to_bytes(4, "big") + ct)
        if last:
            return
        buf, counter = nxt, counter + 1


def _read_exact(src: BinaryIO, n: int) -> bytes:
    data = src.read(n)
    while len(data) < n:
        more = src.read(n - len(data))
        if not more:
            break
        data += more
    return data


def decrypt_stream(src: BinaryIO, dst: BinaryIO, passphrase: str) -> None:
    if not passphrase:
        raise CryptoError("BACKUP_PASSPHRASE fehlt")
    header = _read_exact(src, len(BACKUP_MAGIC) + 24)
    if len(header) != len(BACKUP_MAGIC) + 24 or not header.startswith(BACKUP_MAGIC):
        raise CryptoError("Keine verschlüsselte Sicherungsdatei (Kopfdaten fehlen)")
    salt, prefix = header[len(BACKUP_MAGIC):len(BACKUP_MAGIC) + 16], header[-8:]
    aes = AESGCM(_derive(passphrase, salt))
    counter = 0
    ln = _read_exact(src, 4)
    if len(ln) != 4:
        raise CryptoError("Sicherungsdatei ist abgeschnitten")
    while True:
        size = int.from_bytes(ln, "big")
        ct = _read_exact(src, size)
        if len(ct) != size:
            raise CryptoError("Sicherungsdatei ist abgeschnitten")
        ln = _read_exact(src, 4)
        last = len(ln) == 0
        if 0 < len(ln) < 4:
            raise CryptoError("Sicherungsdatei ist beschädigt")
        try:
            dst.write(aes.decrypt(prefix + counter.to_bytes(4, "big"), ct, header + (b"\x01" if last else b"\x00")))
        except InvalidTag as e:
            raise CryptoError("Entschlüsselung fehlgeschlagen: falsche Passphrase, beschädigte oder abgeschnittene Datei") from e
        if last:
            return
        counter += 1
