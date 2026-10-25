"""Powiadomienia w HA: trwałe powiadomienie, opcjonalna usługa notify.* i zdarzenie gpk_water_event."""
import logging

from . import ha_out

log = logging.getLogger("gpk.notify")


def send(title: str, message: str, kind: str = "info", notify_service: str = "", nid: str | None = None) -> bool:
    msgs = [
        {"type": "call_service", "domain": "persistent_notification", "service": "create",
         "service_data": {"title": title, "message": message, "notification_id": nid or f"gpk_water_{kind}"}},
        {"type": "fire_event", "event_type": "gpk_water_event", "event_data": {"kind": kind, "title": title, "message": message}},
    ]
    svc = (notify_service or "").strip()
    if svc.startswith("notify."):
        msgs.append({"type": "call_service", "domain": "notify", "service": svc.split(".", 1)[1],
                     "service_data": {"title": title, "message": message}})
    try:
        res = ha_out.ws_batch(msgs)
    except Exception as e:  # noqa: BLE001
        log.warning("powiadomienie nie wysłane: %s", e)
        return False
    if res is None:
        log.warning("powiadomienie nie wysłane: %s", ha_out.LAST_WS_ERROR)
        return False
    return True
