"""Powiadomienia: kiedy i o czym dodatek daje znać (ustawiane w zakładce Powiadomienia).

Kanały: trwałe powiadomienie w HA (zawsze), opcjonalnie usługa notify.* (telefon) oraz zdarzenie gpk_water_event
do własnych automatyzacji. W godzinach ciszy nocnej telefon nie dostaje nic, a powiadomienie w HA zostaje.
Każde zdarzenie ma klucz zapisany w bazie, więc po restarcie nic nie wysyła się dwa razy.
"""
import logging
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import ha_out, meters, notify, state

log = logging.getLogger("gpk.notifications")

EVENTS = {  # klucz: (nazwa, opis, domyślnie włączone, parametry)
    "new_invoice": ("Nowa faktura", "Zaraz po pojawieniu się faktury: kwota, termin, okres, zużycie, porównanie z poprzednią.", True, {}),
    "price_change": ("Zmiana cen", "Gdy cena wody lub ścieków jest inna niż na poprzedniej fakturze.", True, {}),
    "high_invoice": ("Wysoka faktura", "Faktura (przeliczona na dobę) wyższa o tyle % od średniej z 12 miesięcy.", True, {"percent": 30}),
    "interest": ("Nota odsetkowa", "Na fakturze jest nota odsetkowa, czyli płatność była spóźniona.", True, {}),
    "usage_spike": ("Nietypowe zużycie domu", "Wczorajsze zużycie domu (licznik główny minus podlicznik) wyższe o tyle razy od typowego dnia.", True, {"factor": 3, "min_m3": 1.5}),
    "no_invoice": ("Brak faktury po odczytach", "Minęło tyle dni od wysłania stanów liczników, a faktury nie ma.", True, {"days": 10}),
    "readings_sent": ("Wysłano stany liczników", "Po automatycznej lub ręcznej wysyłce odczytów do GPK.", True, {}),
    "readings_failed": ("Problem z wysyłką odczytów", "Wysyłka nie powiodła się (po 3 próbach) albo okno wysyłki minęło.", True, {}),
    "sync_problem": ("Problem z pocztą lub fakturą", "Nie udało się odczytać PDF z faktury albo synchronizacja poczty ciągle się nie udaje.", True, {}),
}
DEFAULTS = dict(notify_services=[], persistent=True, quiet=True, quiet_from="22:00", quiet_to="07:00")


def get_settings() -> dict:
    saved = dict(meters._read_all().get("notifications") or {})
    if saved.get("notify_service") and not saved.get("notify_services"):  # migracja ze starego pola
        saved["notify_services"] = [saved["notify_service"]]
    saved.pop("notify_service", None)
    s = {**DEFAULTS, **{k: v for k, v in saved.items() if k != "events"}}
    ev = {}
    for k, (_, _, on, params) in EVENTS.items():
        cur = (saved.get("events") or {}).get(k) or {}
        ev[k] = {"enabled": cur.get("enabled", on), **{p: cur.get(p, d) for p, d in params.items()}}
    s["events"] = ev
    return s


def save_settings(new: dict) -> dict:
    s = dict(DEFAULTS)
    raw = new.get("notify_services")
    if raw is None:
        raw = [new.get("notify_service")] if new.get("notify_service") else []
    s["notify_services"] = sorted({("notify." + x if not x.startswith("notify.") else x) for x in (str(v).strip() for v in raw) if x})
    s["persistent"] = bool(new.get("persistent", True))
    s["quiet"] = bool(new.get("quiet", True))
    for k in ("quiet_from", "quiet_to"):
        v = str(new.get(k) or DEFAULTS[k])
        if len(v) != 5 or v[2] != ":" or not (v[:2] + v[3:]).isdigit():
            raise ValueError("Godziny w formacie GG:MM")
        s[k] = v
    ev = {}
    for k, (_, _, on, params) in EVENTS.items():
        cur = (new.get("events") or {}).get(k) or {}
        ev[k] = {"enabled": bool(cur.get("enabled", on))}
        for p, d in params.items():
            try:
                ev[k][p] = float(cur.get(p, d))
            except (TypeError, ValueError):
                raise ValueError(f"Nieprawidłowa wartość: {EVENTS[k][0]}") from None
            if ev[k][p] <= 0:
                raise ValueError(f"{EVENTS[k][0]}: wartość musi być dodatnia")
    s["events"] = ev
    allv = meters._read_all()
    allv["notifications"] = s
    meters._write_all(allv)
    return get_settings()


def _tz():
    try:
        return ZoneInfo(getattr(meters, "TZ_NAME", None) or "Europe/Warsaw")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Europe/Warsaw")


def in_quiet(s: dict, now: datetime | None = None) -> bool:
    if not s["quiet"]:
        return False
    now = now or datetime.now(_tz())
    cur = now.strftime("%H:%M")
    a, b = s["quiet_from"], s["quiet_to"]
    return (a <= cur or cur < b) if a > b else (a <= cur < b)


def emit(store, kind: str, title: str, message: str, key: str, now: datetime | None = None, short: str | None = None) -> bool:
    """Wysyła powiadomienie, jeśli to zdarzenie jest włączone i jeszcze go nie wysłano (klucz)."""
    s = get_settings()
    if not s["events"].get(kind, {}).get("enabled", False):
        return False
    if store.was_notified(key):
        return False
    phone = [] if in_quiet(s, now) else s["notify_services"]
    ok = notify.send(title, message, kind, phone, key, persistent=s["persistent"], phone_message=short)
    store.log_notification(key, kind, title, message, ok)
    return ok


SAMPLES = {  # rodzaj: (tytuł, krótka treść na telefon, pełna treść w HA)
    "new_invoice": ("🧾 Faktura GPK 194,00 zł", "Do 15.10 · 14 m³ · +6% na dobę",
                    "Okres 01.08–30.09 (61 dni) · 14 m³ (dom 10, ogród 4)\nTermin płatności: 15.10.2026\nRealny koszt 1 m³ (dom): 17,00 zł\nNa dobę drożej o 6% niż poprzednio (183,00 zł)"),
    "price_change": ("💧 Zmiana cen wody i ścieków", "woda 7,70 → 7,95; ścieki 9,10 → 9,50",
                     "woda 7,70 → 7,95 zł netto/m³ (+3,2%)\nścieki 9,10 → 9,50 zł netto/m³ (+4,4%)"),
    "high_invoice": ("⚠️ Faktura +42% ponad średnią", "312,00 zł, średnio 220,00 zł", "Na dobę 5,11 zł wobec średniej 3,60 zł z 12 miesięcy (+42%)."),
    "interest": ("⚠️ Nota odsetkowa 4,20 zł", "Sprawdź, czy poprzednia faktura jest opłacona", "Do faktury 123/2026 dołączono notę odsetkową. Sprawdź, czy poprzednia faktura jest opłacona."),
    "usage_spike": ("🚰 Wczoraj 3,2 m³ w domu", "Zwykle 0,4 m³, sprawdź wyciek", "24.10.2026: dom zużył 3,2 m³ (zwykle ok. 0,4 m³ na dobę), ogród 0,0 m³. Sprawdź, czy nie ma wycieku."),
    "no_invoice": ("📭 Brak faktury 10 dni po odczytach", "Odczyty wysłane 02.10", "Odczyty wysłano 02.10, a faktury nadal nie ma (10 dni). Sprawdź pocztę lub portal eBOK."),
    "readings_sent": ("✅ Odczyty wysłane: 1647,8 m³", "Ogród 214,3 m³ · do GPK", "Stan licznika głównego: 1647,8 m³\nPodlicznik (ogród): 214,3 m³\nDo: faktury@gpkszemud.pl"),
    "readings_failed": ("❌ Odczyty nie wysłane", "Błąd poczty, ponawiam", "Dodatek próbuje ponownie co 10 minut. Powód: błąd poczty (przykład)."),
    "sync_problem": ("❌ Nie odczytano faktury z maila", "1 PDF do sprawdzenia w Statusie", "1 mail(i) z PDF nie zostały sparsowane. Możliwy nowy format faktury. Pobierz je w zakładce Status."),
}


def test(store, services: list | None = None, kind: str | None = None) -> dict:
    """Próbne powiadomienie (ogólne albo przykład wskazanego zdarzenia) na wskazane lub zapisane urządzenia."""
    s = get_settings()
    svcs = s["notify_services"] if services is None else [("notify." + x if not x.startswith("notify.") else x) for x in services if x]
    if kind in SAMPLES:
        t, sh, full = SAMPLES[kind]
        ok = notify.send("[próba] " + t, full, "test", svcs, "gpk_water_test_" + kind, persistent=True, phone_message=sh)
    else:
        ok = notify.send("GPK Szemud: test powiadomień", "Jeśli to widzisz, powiadomienia działają.", "test", svcs,
                         "gpk_water_test", persistent=True)
    errs = list(notify.LAST.get("errors") or [])
    if not ok and not errs:
        errs = [ha_out.LAST_WS_ERROR or "brak połączenia z HA"]
    return dict(ok=ok, services=svcs, errors=errs)


# ---------- zdarzenia ----------
def _f(v, d=2):
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


def _d(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


def _perday(i):
    return i["invoice_gross"] / max(i["period_days"], 1) if i["period_days"] >= 7 else None


def _home_per_m3(i):
    return (i["gross_water_home"] + i["gross_sewage"] + i["gross_abo"]) / i["water_home_m3"] if i["water_home_m3"] else None


def on_new_invoices(store, now: datetime | None = None):
    """Sprawdza faktury, o których jeszcze nie powiadomiono. Przy pierwszym uruchomieniu stare faktury tylko oznacza."""
    invs = store.invoices()
    first = store.notified_count() == 0
    s = get_settings()["events"]
    for idx, i in enumerate(invs):
        key = "inv:" + i["number"]
        if store.was_notified(key):
            continue
        if first:  # pierwsze uruchomienie: istniejące faktury tylko oznaczamy, bez powiadomień
            store.log_notification(key, "seed", i["number"], "", False)
            continue
        prev = invs[idx - 1] if idx else None
        older = [x for x in invs[:idx] if _perday(x) and x["issue_date"] >= (datetime.fromisoformat(i["issue_date"]) - timedelta(days=366)).date().isoformat()]
        lines = [f"Okres {i['period_start'][8:10]}.{i['period_start'][5:7]}–{_d(i['period_end'])[:5]} ({i['period_days']} dni) · "
                 f"{_f(i['water_home_m3'] + i['water_garden_m3'], 0)} m³ (dom {_f(i['water_home_m3'], 0)}, ogród {_f(i['water_garden_m3'], 0)})",
                 f"Termin płatności: {_d(i['due_date'])}"]
        pm = _home_per_m3(i)
        if pm:
            lines.append(f"Realny koszt 1 m³ (dom): {_f(pm)} zł")
        if prev and _perday(i) and _perday(prev):
            ch = (_perday(i) / _perday(prev) - 1) * 100
            lines.append(f"Na dobę {'drożej' if ch > 0 else 'taniej'} o {_f(abs(ch), 0)}% niż poprzednio ({_f(prev['invoice_gross'])} zł)")
        if i.get("interest_amount"):
            lines.append(f"Uwaga: nota odsetkowa {_f(i['interest_amount'])} zł")
        sh = f"Do {_d(i['due_date'])[:5]} · {_f(i['water_home_m3'] + i['water_garden_m3'], 0)} m³"
        if prev and _perday(i) and _perday(prev):
            sh += f" · {'+' if _perday(i) >= _perday(prev) else '-'}{_f(abs(_perday(i) / _perday(prev) - 1) * 100, 0)}% na dobę"
        emit(store, "new_invoice", f"🧾 Faktura GPK {_f(i['invoice_gross'])} zł", "\n".join(lines), key, now, short=sh)
        # powiązane zdarzenia
        if prev:
            parts = []
            for lbl, k in (("woda", "water_price_net"), ("ścieki", "sewage_price_net")):
                if i[k] and prev[k] and abs(i[k] - prev[k]) > 0.004:
                    parts.append(f"{lbl} {_f(prev[k])} → {_f(i[k])} zł netto/m³ ({'+' if i[k] > prev[k] else ''}{_f((i[k] / prev[k] - 1) * 100, 1)}%)")
            if parts:
                emit(store, "price_change", "💧 Zmiana cen wody i ścieków", "\n".join(parts), "price:" + i["number"], now, short="; ".join(parts))
        if older and _perday(i):
            avg = sum(x["invoice_gross"] for x in older) / sum(x["period_days"] for x in older if _perday(x))
            lim = s["high_invoice"]["percent"]
            if _perday(i) > avg * (1 + lim / 100):
                emit(store, "high_invoice", f"⚠️ Faktura +{_f((_perday(i) / avg - 1) * 100, 0)}% ponad średnią",
                     f"Na dobę {_f(_perday(i))} zł wobec średniej {_f(avg)} zł z 12 miesięcy (+{_f((_perday(i) / avg - 1) * 100, 0)}%).", "high:" + i["number"], now, short=f"{_f(i['invoice_gross'])} zł, średnio {_f(avg * i['period_days'])} zł")
        if i.get("interest_amount"):
            emit(store, "interest", f"⚠️ Nota odsetkowa {_f(i['interest_amount'])} zł",
                 f"Do faktury {i['number']} dołączono notę odsetkową {i.get('interest_note') or ''}. Sprawdź, czy poprzednia faktura jest opłacona.", "int:" + i["number"], now, short="Sprawdź, czy poprzednia faktura jest opłacona")


def check_usage(store, daily: list[dict], now: datetime | None = None):
    """daily: lista dni z liczników ({d, home, sub, main}). Sprawdza ostatni zamknięty dzień (wczoraj)."""
    ev = get_settings()["events"]["usage_spike"]
    if not ev["enabled"] or len(daily) < 10:
        return
    now = now or datetime.now(_tz())
    yday = (now.date() - timedelta(days=1)).isoformat()
    row = next((r for r in daily if r["d"] == yday), None)
    if not row:
        return
    base = [r["home"] for r in daily if r["d"] < yday][-30:]
    med = statistics.median(base) if base else 0
    lim = max(ev["min_m3"], ev["factor"] * med)
    if row["home"] > lim:
        emit(store, "usage_spike", f"🚰 Wczoraj {_f(row['home'], 1)} m³ w domu",
             f"{_d(yday)}: dom zużył {_f(row['home'], 1)} m³ (zwykle ok. {_f(med, 1)} m³ na dobę), ogród {_f(row['sub'], 1)} m³. "
             "Sprawdź, czy nie ma wycieku, a woda do ogrodu idzie przez podlicznik.", "spike:" + yday, now, short=f"Zwykle {_f(med, 1)} m³, sprawdź wyciek")


def check_no_invoice(store, now: datetime | None = None):
    ev = get_settings()["events"]["no_invoice"]
    if not ev["enabled"]:
        return
    now = now or datetime.now(_tz())
    sub = next((r for r in store.submissions() if r["status"] == "sent" and r["sent_at"]), None)
    if not sub:
        return
    sent = datetime.fromisoformat(sub["sent_at"])
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=_tz())
    if now - sent < timedelta(days=ev["days"]):
        return
    if any(i["issue_date"] >= sent.date().isoformat() for i in store.invoices()):
        return
    emit(store, "no_invoice", f"📭 Brak faktury {int(ev['days'])} dni po odczytach",
         f"Odczyty wysłano {sent.strftime('%d.%m')}, a faktury nadal nie ma ({int(ev['days'])} dni). Sprawdź pocztę lub portal eBOK.",
         "noinv:" + sub["month"], now, short=f"Odczyty wysłane {sent.strftime('%d.%m')}")


def check_sync(store, now: datetime | None = None):
    st = state.snapshot()
    failed = store.failed_mails()
    if failed:
        emit(store, "sync_problem", "❌ Nie odczytano faktury z maila",
             f"{len(failed)} mail(i) z PDF nie zostały sparsowane. Możliwy nowy format faktury. Pobierz je w zakładce Status.",
             "parse:" + ",".join(sorted(f["uid"] for f in failed))[:200], now, short=f"{len(failed)} PDF do sprawdzenia w Statusie")
    if st.get("last_error") and st.get("last_ok") is None and st.get("last_run"):
        emit(store, "sync_problem", "❌ Synchronizacja poczty nie działa", str(st["last_error"])[:300],
             "sync:" + datetime.now(_tz()).strftime("%Y-%m-%d"), now, short=str(st["last_error"])[:80])


def list_services() -> list[dict]:
    """Usługi notify.* z HA (telefony z aplikacją, grupy, Telegram itd.). Puste, gdy HA niedostępne."""
    res = ha_out.ws_batch([{"type": "get_services"}])
    if not res or not isinstance(res[0], dict):
        return []
    out = []
    for name, d in (res[0].get("notify") or {}).items():
        if name in ("send_message", "persistent_notification"):
            continue
        label = (d or {}).get("name") or name
        out.append(dict(service="notify." + name, name=name, mobile=name.startswith("mobile_app_")))
    out.sort(key=lambda x: (not x["mobile"], x["name"]))
    return out
