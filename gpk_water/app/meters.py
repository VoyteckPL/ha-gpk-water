"""Wodomierze z HA (np. ESPHome): wybór encji, dzienne zużycie ze statystyk, szacunek kosztu bieżącego okresu."""
import json
import logging
import os
import statistics
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import ha_out

log = logging.getLogger("gpk.meters")
DATA = os.environ.get("GPK_DATA", "/data")
SETTINGS = os.path.join(DATA, "settings.json")
_lock = threading.Lock()
_cache = {"t": 0, "key": None, "data": None}


def load_settings() -> dict:
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            d = json.load(f)
        return {"main": d.get("main") or None, "sub": d.get("sub") or None}
    except (OSError, ValueError):
        return {"main": None, "sub": None}


def save_settings(main: str | None, sub: str | None):
    os.makedirs(DATA, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump({"main": main or None, "sub": sub or None}, f)
    _cache.update(t=0)


def _m3(v, unit) -> float:
    v = float(v or 0)
    return v / 1000 if (unit or "").strip().lower() in ("l", "litr", "litry", "liters", "litres") else v


def candidates() -> list[dict]:
    """Encje, które mogą być wodomierzami: jednostka m³/L albo device_class water."""
    res = ha_out.ws_batch([{"type": "get_states"}])
    out = []
    if res is None:
        return {"error": ha_out.LAST_WS_ERROR or "brak połączenia z HA"}
    for s in (res[0] if res and res[0] else []):
        a = s.get("attributes", {}) or {}
        unit = (a.get("unit_of_measurement") or "")
        if not s["entity_id"].startswith("sensor."):
            continue
        if a.get("device_class") == "water" or unit.lower() in ("m³", "m3", "l"):
            out.append(dict(entity_id=s["entity_id"], name=a.get("friendly_name") or s["entity_id"], unit=unit,
                            state=s.get("state"), state_class=a.get("state_class"), device_class=a.get("device_class")))
    out.sort(key=lambda x: (x["device_class"] != "water", x["entity_id"]))
    return out


def _fetch(main: str, sub: str | None):
    ids = [main] + ([sub] if sub else [])
    since = "2019-01-01T00:00:00+00:00"
    res = ha_out.ws_batch([
        {"type": "get_config"},
        {"type": "recorder/get_statistics_metadata", "statistic_ids": ids},
        {"type": "recorder/statistics_during_period", "start_time": since, "statistic_ids": ids,
         "period": "day", "types": ["change"]},
        {"type": "get_states"},
    ])
    if not res:
        return None
    return dict(config=res[0] or {}, meta=res[1] or [], stats=res[2] or {}, states={s["entity_id"]: s for s in (res[3] or [])})


def compute(invoices: list[dict], settings: dict, raw: dict | None, today: date | None = None) -> dict:
    out = dict(configured=bool(settings.get("main")), settings=settings, error=None)
    if not settings.get("main"):
        return out
    if raw is None:
        out["error"] = "Brak połączenia z API Home Assistant: " + (ha_out.LAST_WS_ERROR or "nieznany powód")
        return out
    tz = ZoneInfo(raw["config"].get("time_zone") or "Europe/Warsaw")
    today = today or datetime.now(tz).date()
    units = {m.get("statistic_id"): m.get("statistic_unit_of_measurement") or m.get("display_unit_of_measurement") for m in raw["meta"]}

    def daily(eid):
        d = {}
        unit = units.get(eid) or (raw["states"].get(eid, {}).get("attributes", {}) or {}).get("unit_of_measurement")
        for row in raw["stats"].get(eid) or []:
            ts = row["start"] / 1000 if row["start"] > 1e11 else row["start"]
            d[datetime.fromtimestamp(ts, tz).date()] = _m3(row.get("change"), unit)
        return d

    main, sub = settings["main"], settings.get("sub")
    dm = daily(main)
    ds = daily(sub) if sub else {}
    cur = {k: raw["states"].get(k, {}) for k in (main, sub) if k}
    out["live"] = {k: dict(state=v.get("state"), unit=(v.get("attributes") or {}).get("unit_of_measurement")) for k, v in cur.items()}
    if not dm:
        out["error"] = ("Brak statystyk dla wybranego licznika. Encja musi mieć state_class: total_increasing "
                        "(w ESPHome np. state_class: total_increasing przy sensorze pulse_meter/total).")
        return out
    days = sorted(dm)
    out["history_from"] = days[0].isoformat()
    out["daily"] = [dict(d=d.isoformat(), main=round(dm[d], 4), sub=round(ds.get(d, 0), 4),
                         home=round(max(dm[d] - ds.get(d, 0), 0), 4)) for d in days]

    if not invoices:
        return out
    L = invoices[-1]
    vat = 1 + (L["vat_rate"] or 8) / 100
    wp, sp, ap = L["water_price_net"] * vat, L["sewage_price_net"] * vat, (L["abo_price_net"] or 0) * vat
    since = date.fromisoformat(L["period_end"])

    def total(dct, a, b):  # dni a < d <= b
        return sum(v for d, v in dct.items() if a < d <= b)

    m_main, m_sub = total(dm, since, today), total(ds, since, today)
    m_home = max(m_main - m_sub, 0)
    n_days = max((today - since).days, 0)
    c_home, c_garden = m_home * (wp + sp), m_sub * wp
    c_abo = ap * n_days / 30.4375
    est_total = c_home + c_garden + c_abo

    # prognoza: tempo z ostatnich 14 pełnych dni × typowa długość okresu
    window = [today - timedelta(days=k) for k in range(1, 15)]
    window = [d for d in window if d in dm]
    typical = statistics.median([i["period_days"] for i in invoices[-6:] if i["period_days"] >= 7] or [30])
    if window:
        a_home = sum(max(dm[d] - ds.get(d, 0), 0) for d in window) / len(window)
        a_sub = sum(ds.get(d, 0) for d in window) / len(window)
        proj = typical * (a_home * (wp + sp) + a_sub * wp) + ap * typical / 30.4375
        lpd = (a_home + a_sub) * 1000
    else:
        proj, lpd = est_total, None
    out["estimate"] = dict(since=since.isoformat(), days=n_days, m3_main=round(m_main, 3), m3_home=round(m_home, 3),
                           m3_garden=round(m_sub, 3), cost_home=round(c_home, 2), cost_garden=round(c_garden, 2),
                           cost_abo=round(c_abo, 2), total=round(est_total, 2), next_invoice=round(max(proj, est_total), 2),
                           typical_days=typical, l_per_day=round(lpd) if lpd else None,
                           prices=dict(water=round(wp, 4), sewage=round(sp, 4), abo=round(ap, 4)))

    # kontrola: licznik HA vs odczyt gminy (okres faktury)
    acc = []
    first = days[0]
    for i in invoices:
        a, b = date.fromisoformat(i["period_start"]), date.fromisoformat(i["period_end"])
        if a < first or b > today:
            continue
        ha_m, ha_s = total(dm, a, b), total(ds, a, b)
        row = dict(number=i["number"], issue_date=i["issue_date"], period_start=i["period_start"], period_end=i["period_end"],
                   inv_main=i["main_usage"], ha_main=round(ha_m, 2))
        row["diff_main_pct"] = round((ha_m / i["main_usage"] - 1) * 100, 1) if i["main_usage"] else None
        if sub:
            row.update(inv_sub=i["sub_usage"], ha_sub=round(ha_s, 2),
                       diff_sub_pct=round((ha_s / i["sub_usage"] - 1) * 100, 1) if i["sub_usage"] else None)
        acc.append(row)
    out["accuracy"] = acc
    return out


def est_values(res: dict) -> dict:
    e = res.get("estimate")
    if not e:
        return {}
    return dict(est_total=e["total"], est_home=e["cost_home"] + e["cost_abo"], est_garden=e["cost_garden"],
                est_m3_home=e["m3_home"], est_m3_garden=e["m3_garden"], est_next_invoice=e["next_invoice"],
                est_days=e["days"], est_l_per_day=e["l_per_day"])


def refresh(store, force=False) -> dict:
    """Wynik z krótkim cache (panel + pętla w tle współdzielą jedno zapytanie)."""
    with _lock:
        s = load_settings()
        key = json.dumps(s, sort_keys=True)
        if not force and _cache["data"] is not None and _cache["key"] == key and time.time() - _cache["t"] < 60:
            return _cache["data"]
        raw = _fetch(s["main"], s["sub"]) if s["main"] else None
        try:
            data = compute(store.invoices(), s, raw)
        except Exception as e:  # noqa: BLE001
            log.exception("błąd liczenia z liczników")
            data = dict(configured=True, settings=s, error=f"{type(e).__name__}: {e}")
        _cache.update(t=time.time(), key=key, data=data)
        return data
