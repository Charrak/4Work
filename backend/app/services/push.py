import json
import logging
import threading

from ..config import settings

log = logging.getLogger("dienstplan.push")


def send_async(subscriptions: list[dict], title: str, body: str) -> None:
    """Web-Push (VAPID) im Hintergrund. Ohne Schlüssel oder pywebpush passiert nichts."""
    if not (settings.vapid_private_key and subscriptions):
        return
    try:
        from pywebpush import webpush
    except ImportError:
        return

    def run() -> None:
        for s in subscriptions:
            try:
                webpush(
                    subscription_info={"endpoint": s["endpoint"],
                                       "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                    data=json.dumps({"title": title, "body": body}),
                    vapid_private_key=settings.vapid_private_key,
                    vapid_claims={"sub": settings.vapid_subject},
                )
            except Exception as e:  # abgelaufene Abos usw. sind normal
                log.info("Push fehlgeschlagen: %s", e)

    threading.Thread(target=run, daemon=True).start()
