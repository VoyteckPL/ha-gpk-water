"""Wyjście do HA: sensory przez MQTT discovery + import historii do statystyk długoterminowych."""
import json
import logging
import os
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

log = logging.getLogger("gpk.ha")

DEV = {"identifiers": ["gpk_water"], "name": "GPK Szemud - woda", "manufacturer": "GPK Szemud", "model": "eBOK faktury"}
PLN = "PLN"
REMOVED = ["last_payable"]

# klucz, nazwa, jednostka, device_class, state_class, ikona
SENSORS = [
    ("last_invoice_gross", "Ostatnia faktura", PLN, "monetary", None, "mdi:receipt-text"),
    ("last_number", "Numer ostatniej faktury", None, None, None, "mdi:numeric"),
    ("last_issue_date", "Data ostatniej faktury", None, "date", None, "mdi:calendar"),
    ("last_due_date", "Termin płatności", None, "date", None, "mdi:calendar-alert"),
    ("last_home_m3", "Woda dom - ostatnia faktura", "m³", "water", None, "mdi:water"),
    ("last_garden_m3", "Woda ogród - ostatnia faktura", "m³", "water", None, "mdi:sprinkler"),
    ("last_sewage_m3", "Ścieki - ostatnia faktura", "m³", None, None, "mdi:pipe"),
    ("water_price_gross", "Cena wody brutto", "PLN/m³", None, None, "mdi:water-plus"),
    ("sewage_price_gross", "Cena ścieków brutto", "PLN/m³", None, None, "mdi:pipe-leak"),
    ("abo_price_gross", "Abonament brutto", "PLN/mies.", None, None, "mdi:calendar-month"),
    ("home_cost_per_m3", "Realny koszt 1 m³ (dom)", "PLN/m³", None, None, "mdi:cash"),
    ("garden_cost_per_m3", "Koszt 1 m³ (ogród)", "PLN/m³", None, None, "mdi:cash"),
    ("daily_cost_last", "Koszt na dobę", "PLN/d", None, None, "mdi:cash-fast"),
    ("monthly_avg_12m", "Średni koszt miesięczny (12 mies.)", "PLN/mies.", None, None, "mdi:chart-line"),
    ("year_m3_home", "Zużycie roczne (dom, szacunek)", "m³/rok", None, None, "mdi:water-sync"),
    ("interest_last", "Odsetki na ostatniej fakturze", PLN, "monetary", None, "mdi:alert-circle-outline"),
    ("invoice_count", "Liczba faktur w bazie", None, None, None, "mdi:database"),
]


def publish(host, port, user, password, values: dict, prefix="homeassistant", sensors=None):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2) if hasattr(mqtt, "CallbackAPIVersion") else mqtt.Client()
    if user:
        c.username_pw_set(user, password)
    c.connect(host, port, 30)
    c.loop_start()
    for old in (REMOVED if sensors is None else []):  # usuń encje wycofane z dodatku
        c.publish(f"{prefix}/sensor/gpk_water/{old}/config", "", retain=True)
    for key, name, unit, dclass, sclass, icon in (sensors or SENSORS):
        cfg = {
            "name": name, "unique_id": f"gpk_water_{key}",
            "state_topic": f"gpk_water/{key}", "device": DEV, "icon": icon,
        }
        if unit:
            cfg["unit_of_measurement"] = unit
        if dclass:
            cfg["device_class"] = dclass
        if sclass:
            cfg["state_class"] = sclass
        c.publish(f"{prefix}/sensor/gpk_water/{key}/config", json.dumps(cfg, ensure_ascii=False), retain=True)
        v = values.get(key)
        if v is not None:
            c.publish(f"gpk_water/{key}", str(v), retain=True)
    c.loop_stop()
    c.disconnect()


# szacunek bieżącego okresu z liczników w HA (osobna lista, publikowana co kilkanaście minut)
SENSORS_EST = [
    ("est_total", "Szacunek od ostatniej faktury", PLN, "monetary", None, "mdi:cash-clock"),
    ("est_home", "Szacunek - dom od faktury", PLN, "monetary", None, "mdi:home-water"),
    ("est_garden", "Szacunek - ogród od faktury", PLN, "monetary", None, "mdi:sprinkler"),
    ("est_m3_home", "Zużycie dom od faktury", "m³", "water", None, "mdi:water"),
    ("est_m3_garden", "Zużycie ogród od faktury", "m³", "water", None, "mdi:sprinkler-variant"),
    ("est_next_invoice", "Szacowana następna faktura", PLN, "monetary", None, "mdi:receipt-text-clock"),
    ("est_days", "Dni od ostatniej faktury", "d", None, None, "mdi:calendar-clock"),
    ("est_l_per_day", "Średnie zużycie (14 dni)", "l/d", None, None, "mdi:water-sync"),
]


# --- historia -> statystyki długoterminowe (recorder/import_statistics) ---

STAT_SERIES = [
    # statistic_id, nazwa, jednostka, funkcja(inv) -> wartość przyrostu
    ("gpk_water:cost_total", "GPK woda - koszt (faktury)", PLN, lambda i: i["invoice_gross"]),
    ("gpk_water:cost_home", "GPK woda - koszt dom", PLN, lambda i: i["gross_water_home"] + i["gross_sewage"] + i["gross_abo"]),
    ("gpk_water:cost_garden", "GPK woda - koszt ogród", PLN, lambda i: i["gross_water_garden"]),
    ("gpk_water:usage_home", "GPK woda - zużycie dom (faktury)", "m³", lambda i: i["water_home_m3"]),
    ("gpk_water:usage_garden", "GPK woda - zużycie ogród (faktury)", "m³", lambda i: i["water_garden_m3"]),
]


def import_history(invoices: list[dict]):
    """Każda faktura = jeden punkt w godzinie wystawienia; sum rośnie narastająco."""
    ws = _ws()
    if ws is None:
        log.warning("import statystyk pominięty: %s", LAST_WS_ERROR)
        return
    mid = 1
    for sid, name, unit, fn in STAT_SERIES:
        total, rows = 0.0, []
        for inv in invoices:
            total += fn(inv)
            start = datetime.fromisoformat(inv["issue_date"]).replace(hour=12, tzinfo=timezone.utc)
            rows.append({"start": start.isoformat(), "state": round(fn(inv), 2), "sum": round(total, 2)})
        ws.send(json.dumps({
            "id": mid, "type": "recorder/import_statistics",
            "metadata": {"has_mean": False, "has_sum": True, "name": name, "source": "gpk_water",
                         "statistic_id": sid, "unit_of_measurement": unit},
            "stats": rows,
        }))
        res = json.loads(ws.recv())
        if not res.get("success"):
            log.error("import %s nieudany: %s", sid, res)
        mid += 1
    ws.close()
    log.info("zaimportowano historię: %d faktur, %d serii", len(invoices), len(STAT_SERIES))


LAST_WS_ERROR = None
TOKEN_FILES = ("/run/s6/container_environment/SUPERVISOR_TOKEN", "/var/run/s6/container_environment/SUPERVISOR_TOKEN")


def _token():
    for k in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    for p in TOKEN_FILES:  # dodatki z s6-overlay: token bywa tylko w pliku
        try:
            t = open(p, encoding="utf-8").read().strip()
            if t:
                return t
        except OSError:
            pass
    return None


def _ws():
    """Połączenie z websocket HA przez Supervisora; None + LAST_WS_ERROR z powodem, gdy się nie da."""
    global LAST_WS_ERROR
    import websocket
    token = _token()
    if not token:
        LAST_WS_ERROR = "brak tokenu Supervisora w środowisku dodatku (SUPERVISOR_TOKEN)"
        return None
    try:
        ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=15)
        ws.recv()
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        r = json.loads(ws.recv())
    except Exception as e:  # noqa: BLE001
        LAST_WS_ERROR = f"połączenie z ws://supervisor/core/websocket nieudane: {type(e).__name__}: {e}"
        return None
    if r.get("type") != "auth_ok":
        ws.close()
        LAST_WS_ERROR = f"HA odrzuciło autoryzację ({r.get('message') or r.get('type')}); sprawdź, czy dodatek ma uprawnienie homeassistant_api"
        return None
    LAST_WS_ERROR = None
    return ws


def ws_batch(msgs: list, errors: list | None = None) -> list | None:
    """Wysyła komendy websocket HA po kolei; zwraca listę wyników (None przy błędzie komendy)."""
    ws = _ws()
    if ws is None:
        return None
    out = []
    try:
        for n, m in enumerate(msgs, 1):
            ws.send(json.dumps({**m, "id": n}))
            while True:
                r = json.loads(ws.recv())
                if r.get("id") == n:
                    out.append(r.get("result") if r.get("success") else None)
                    if not r.get("success") and errors is not None:
                        e = r.get("error") or {}
                        errors.append(f"{m.get('domain', m.get('type'))}.{m.get('service', '')}: {e.get('message') or e.get('code') or 'błąd'}")
                    break
    finally:
        ws.close()
    return out


def fetch_ha_entities() -> dict:
    """unique_id -> {entity_id, state, unit, last_updated} - prawdziwe encje utworzone w HA."""
    out = {}
    try:
        ws = _ws()
        if ws is None:
            return out
        ws.send(json.dumps({"id": 1, "type": "config/entity_registry/list"}))
        reg = json.loads(ws.recv()).get("result") or []
        ws.send(json.dumps({"id": 2, "type": "get_states"}))
        states = {s["entity_id"]: s for s in (json.loads(ws.recv()).get("result") or [])}
        ws.close()
        for e in reg:
            uid = e.get("unique_id") or ""
            if e.get("platform") == "mqtt" and uid.startswith("gpk_water_"):
                st = states.get(e["entity_id"], {})
                out[uid] = dict(entity_id=e["entity_id"], state=st.get("state"),
                                last_updated=st.get("last_updated"), disabled=bool(e.get("disabled_by")))
    except Exception as ex:  # noqa: BLE001
        log.warning("nie udało się odczytać encji z HA: %s", ex)
    return out
