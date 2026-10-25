"""Powiadomienia w HA: trwałe powiadomienie, opcjonalna usługa notify.* i zdarzenie gpk_water_event."""
import logging

from . import ha_out

log = logging.getLogger("gpk.notify")
LAST: dict = {"errors": []}


def _data(svc: str, title: str, message: str) -> dict:
    d = {"title": title, "message": message}
    if svc.startswith("notify.mobile_app_"):
        # tapnięcie nie otwiera aplikacji, tylko rozwija pełną treść (Android); długi tekst w stylu "bigtext"
        d["data"] = {"clickAction": "noAction", "tag": "gpk_water", "group": "gpk_water"}
    return d


def send(title: str, message: str, kind: str = "info", notify_service: str = "", nid: str | None = None,
         persistent: bool = True) -> bool:
    msgs = [
        {"type": "call_service", "domain": "persistent_notification", "service": "create",
         "service_data": {"title": title, "message": message, "notification_id": (nid or f"gpk_water_{kind}").replace(":", "_")}},
        {"type": "fire_event", "event_type": "gpk_water_event", "event_data": {"kind": kind, "title": title, "message": message}},
    ]
    if not persistent:
        msgs.pop(0)
    svcs = [notify_service] if isinstance(notify_service, str) else list(notify_service or [])
    for svc in svcs:
        svc = (svc or "").strip()
        if svc.startswith("notify."):
            msgs.append({"type": "call_service", "domain": "notify", "service": svc.split(".", 1)[1],
                         "service_data": _data(svc, title, message)})
    errors: list = []
    LAST["errors"] = errors
    try:
        res = ha_out.ws_batch(msgs, errors)
    except Exception as e:  # noqa: BLE001
        log.warning("powiadomienie nie wysłane: %s", e)
        return False
    if res is None:
        log.warning("powiadomienie nie wysłane: %s", ha_out.LAST_WS_ERROR)
        return False
    if errors:
        log.warning("powiadomienie: błędy HA: %s", "; ".join(errors))
        return False
    return True
