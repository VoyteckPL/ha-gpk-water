"""Wyjście do HA: sensory przez MQTT discovery + import historii do statystyk długoterminowych."""
import json
import logging
import os
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

log = logging.getLogger("gpk.ha")

DEV = {"identifiers": ["gpk_water"], "name": "GPK Szemud - woda", "manufacturer": "GPK Szemud", "model": "eBOK faktury"}
PLN = "PLN"

# klucz, nazwa, jednostka, device_class, state_class, ikona
SENSORS = [
    ("last_invoice_gross", "Ostatnia faktura", PLN, "monetary", None, "mdi:receipt-text"),
    ("last_payable", "Do zapłaty (z odsetkami)", PLN, "monetary", None, "mdi:cash-clock"),
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


def publish(host, port, user, password, values: dict, prefix="homeassistant"):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2) if hasattr(mqtt, "CallbackAPIVersion") else mqtt.Client()
    if user:
        c.username_pw_set(user, password)
    c.connect(host, port, 30)
    c.loop_start()
    for key, name, unit, dclass, sclass, icon in SENSORS:
        cfg = {
            "name": name, "unique_id": f"gpk_water_{key}", "object_id": f"gpk_woda_{key}",
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
    import websocket  # websocket-client

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.info("brak SUPERVISOR_TOKEN - pomijam import statystyk")
        return
    ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=30)
    ws.recv()
    ws.send(json.dumps({"type": "auth", "access_token": token}))
    if json.loads(ws.recv()).get("type") != "auth_ok":
        raise RuntimeError("autoryzacja websocket HA nieudana")
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
