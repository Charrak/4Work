"""Ermittlung der Client-IP hinter einem Reverse Proxy (ohne Framework-Abhängigkeiten, gut testbar)."""
import ipaddress
from typing import Iterable, Optional


def _parse(value: str):
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def parse_networks(cidrs: Iterable[str]):
    nets = []
    for c in cidrs:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            continue
    return nets


def resolve_client_ip(peer: Optional[str], xff: Optional[str], trust_proxy: bool, trusted_cidrs: Iterable[str]) -> str:
    """Gibt die IP des echten Clients zurück.

    * Ohne TRUST_PROXY zählt nur die direkte Verbindung (X-Forwarded-For wird ignoriert).
    * Mit TRUST_PROXY wird X-Forwarded-For nur ausgewertet, wenn die direkte Verbindung von einem
      vertrauenswürdigen Proxy (TRUSTED_PROXIES) kommt. Die Kette wird von rechts gelesen; die erste
      nicht vertrauenswürdige Adresse ist der Client. Vom Client mitgeschickte, gefälschte Einträge links
      davon werden damit nie benutzt.
    """
    peer_ip = _parse(peer or "")
    if not trust_proxy or peer_ip is None or not xff:
        return peer or "unknown"
    nets = parse_networks(trusted_cidrs)
    if not any(peer_ip in n for n in nets):
        return peer or "unknown"
    for part in reversed([p for p in xff.split(",") if p.strip()]):
        ip = _parse(part)
        if ip is None:
            return peer or "unknown"          # kaputte Kette: lieber die Proxy-Adresse als eine erfundene
        if not any(ip in n for n in nets):
            return str(ip)
    return peer or "unknown"
