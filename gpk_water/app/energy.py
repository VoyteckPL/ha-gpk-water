"""Statystyki dla panelu Energia (sekcja Woda): ciągła historia od pierwszej faktury.

Jedna seria dzienna na każdy z czterech szeregów (zużycie i koszt, dom i ogród). Każdy dzień ma jedną wartość
(godz. 12:00), więc ponowny import nadpisuje te same wiersze - nic się nie dubluje.

* okres objęty fakturą: sumy dokładnie z faktury (m³ i zł); jeśli liczniki w HA mają dane z tego okresu,
  rozkład na dni bierzemy z liczników, w przeciwnym razie rozkładamy równo;
* okres po ostatniej fakturze: zużycie z liczników, koszt = zużycie × ostatnie ceny (+ abonament na dobę);
  gdy przyjdzie faktura, te dni są automatycznie zastępowane danymi z faktury.
"""
import logging
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import ha_out, meters

log = logging.getLogger("gpk.energy")
PLN = "PLN"
SERIES = [  # id, nazwa, jednostka, klasa jednostki, klucz
    ("gpk_water:water_home_m3", "Woda dom - zużycie (Energia)", "m³", "volume", "home_m3"),
    ("gpk_water:water_garden_m3", "Woda ogród - zużycie (Energia)", "m³", "volume", "garden_m3"),
    ("gpk_water:water_home_cost", "Woda dom - koszt (Energia)", PLN, None, "home_cost"),
    ("gpk_water:water_garden_cost", "Woda ogród - koszt (Energia)", PLN, None, "garden_cost"),
]
OLD_IDS = ["gpk_water:cost_total", "gpk_water:cost_home", "gpk_water:cost_garden", "gpk_water:usage_home", "gpk_water:usage_garden"]
LAST = {"time": None, "rows": 0, "from": None, "to": None, "metered_days": 0, "error": None}


def _days(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def build(invoices: list[dict], dm: dict, ds: dict, today: date) -> dict:
    """Zwraca {date: {home_m3, garden_m3, home_cost, garden_cost}} (wartości dzienne, nie narastające)."""
    out: dict = {}
    metered = 0
    prev_end = None
    for inv in sorted(invoices, key=lambda i: (i["period_start"], i["issue_date"])):
        a, b = date.fromisoformat(inv["period_start"]), date.fromisoformat(inv["period_end"])
        start = a + timedelta(days=1)
        if prev_end and start <= prev_end:
            start = prev_end + timedelta(days=1)
        if start > b:
            continue
        prev_end = max(prev_end, b) if prev_end else b
        days = list(_days(start, b))
        n = len(days)
        have = [d for d in days if d in dm]
        use_meters = len(have) >= 0.9 * n
        w_h = {d: max(dm.get(d, 0) - ds.get(d, 0), 0) for d in days} if use_meters else {}
        w_g = {d: ds.get(d, 0) for d in days} if use_meters else {}
        if use_meters:
            metered += n
        sh, sg = sum(w_h.values()), sum(w_g.values())
        flat = {d: 1 / n for d in days}
        wh = {d: w_h[d] / sh for d in days} if use_meters and sh > 0 else flat
        wg = {d: w_g[d] / sg for d in days} if use_meters and sg > 0 else flat
        abo = (inv.get("gross_abo") or 0) / n
        for d in days:
            out[d] = dict(
                home_m3=inv["water_home_m3"] * wh[d], garden_m3=inv["water_garden_m3"] * wg[d],
                home_cost=(inv["gross_water_home"] + inv["gross_sewage"]) * wh[d] + abo,
                garden_cost=inv["gross_water_garden"] * wg[d])
    # ogon: dni po ostatniej fakturze - dane z liczników
    if invoices and dm:
        L = sorted(invoices, key=lambda i: i["period_end"])[-1]
        vat = 1 + (L["vat_rate"] or 8) / 100
        wp, sp = L["water_price_net"] * vat, L["sewage_price_net"] * vat
        abo_day = (L["abo_price_net"] or 0) * vat / 30.4375
        for d in _days(date.fromisoformat(L["period_end"]) + timedelta(days=1), today):
            if d not in dm:
                continue
            g = ds.get(d, 0)
            h = max(dm[d] - g, 0)
            out[d] = dict(home_m3=h, garden_m3=g, home_cost=h * (wp + sp) + abo_day, garden_cost=g * wp)
            metered += 1
    LAST["metered_days"] = metered
    return out


def to_rows(daily: dict, key: str, tz: ZoneInfo) -> list[dict]:
    total, rows = 0.0, []
    for d in sorted(daily):
        v = daily[d][key]
        total += v
        start = datetime.combine(d, dtime(12, 0), tzinfo=tz).astimezone(timezone.utc)
        rows.append({"start": start.isoformat(), "state": round(v, 4), "sum": round(total, 4)})
    return rows


def _meta(sid, name, unit, uclass, with_class=True):
    m = {"has_mean": False, "has_sum": True, "name": name, "source": "gpk_water", "statistic_id": sid, "unit_of_measurement": unit}
    if with_class and uclass:
        m["unit_class"] = uclass
    return m


def import_all(store, force_clear_old: bool = False) -> dict:
    """Przebudowuje i importuje wszystkie cztery serie. Bezpieczne do wielokrotnego wywołania."""
    invoices = store.invoices()
    if not invoices:
        return LAST
    s = meters.load_settings()
    dm, ds, tzname = {}, {}, None
    if s["main"]:
        raw = meters._fetch(s["main"], s["sub"])
        if raw:
            tzname = raw["config"].get("time_zone")
            dm, ds = meters.daily_maps(raw, s)
    tz = ZoneInfo(tzname or getattr(meters, "TZ_NAME", None) or "Europe/Warsaw")
    daily = build(invoices, dm, ds, datetime.now(tz).date())
    msgs, plan = [], []
    if force_clear_old or not meters._read_all().get("old_stats_cleared"):
        msgs.append({"type": "recorder/clear_statistics", "statistic_ids": OLD_IDS})
        plan.append("clear")
    for sid, name, unit, uclass, key in SERIES:
        msgs.append({"type": "recorder/import_statistics", "metadata": _meta(sid, name, unit, uclass),
                     "stats": to_rows(daily, key, tz)})
        plan.append(sid)
    res = ha_out.ws_batch(msgs)
    if res is None:
        LAST["error"] = ha_out.LAST_WS_ERROR or "brak połączenia z HA"
        return LAST
    if any(r is None for r in res):  # starszy HA może nie znać unit_class - ponów bez niego
        res2 = ha_out.ws_batch([{"type": "recorder/import_statistics", "metadata": _meta(sid, name, unit, uclass, False),
                                 "stats": to_rows(daily, key, tz)} for sid, name, unit, uclass, key in SERIES])
        if res2 is None or any(r is None for r in res2):
            LAST["error"] = "HA odrzuciło import statystyk (recorder/import_statistics)"
            return LAST
    if "clear" in plan:
        d = meters._read_all()
        d["old_stats_cleared"] = True
        meters._write_all(d)
    days = sorted(daily)
    LAST.update(time=time.time(), rows=len(days), error=None, **{"from": days[0].isoformat(), "to": days[-1].isoformat()})
    log.info("panel Energia: zaimportowano %d dni (%s - %s), w tym %d z liczników", len(days), days[0], days[-1], LAST["metered_days"])
    return LAST
