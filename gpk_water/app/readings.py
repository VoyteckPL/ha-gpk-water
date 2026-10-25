"""Miesięczna wysyłka stanów liczników do GPK.

Stan jest w bazie (SQLite), więc restart dodatku, brak internetu albo niedostępny HA niczego nie gubią:
co minutę tick() sprawdza, czy za bieżący miesiąc odczyt został wysłany, a jeśli termin minął, próbuje
(co 10 minut) aż do końca okna. Ochrona przed dublem: po awarii w trakcie wysyłki sprawdzamy w Gmailu,
czy mail z nagłówkiem X-GPK-Water-Month już wyszedł.
"""
import logging
import os
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import ha_out, mailer, meters, notifications

log = logging.getLogger("gpk.readings")
RETRY_S = 600
GPK_ADDR = "faktury@gpkszemud.pl"
DEFAULTS = dict(enabled=False, day=1, time="08:00", window_days=5, to_gpk=True, extra="", cc_self=False,
                subject="Stan liczników wody", address="", intro="Stany liczników na dzień:", sanity=True)
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


class Unavailable(Exception):
    """Licznik lub HA chwilowo niedostępny - spróbujemy ponownie."""


class SanityError(Exception):
    """Odczyt wygląda błędnie (mniejszy niż poprzedni) - nie wysyłamy automatycznie."""


def emails(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,;\s]+", text or "") if x.strip()]


def get_settings() -> dict:
    s = {**DEFAULTS, **(meters._read_all().get("readings") or {})}
    return s


def save_settings(new: dict) -> dict:
    s = dict(DEFAULTS)
    s["enabled"] = bool(new.get("enabled"))
    s["day"] = int(new.get("day", 1))
    if not 1 <= s["day"] <= 28:
        raise ValueError("Dzień miesiąca musi być z zakresu 1-28")
    t = str(new.get("time", "08:00"))
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", t):
        raise ValueError("Godzina w formacie GG:MM")
    s["time"] = t
    s["window_days"] = int(new.get("window_days", 5))
    if not 1 <= s["window_days"] <= 20:
        raise ValueError("Okno ponawiania: 1-20 dni")
    s["to_gpk"] = bool(new.get("to_gpk", True))
    s["extra"] = ", ".join(emails(new.get("extra", "")))
    s["cc_self"] = bool(new.get("cc_self", False))
    if not all(EMAIL.match(x) for x in emails(s["extra"])):
        raise ValueError("Dodatkowy adres e-mail jest niepoprawny")
    if not s["to_gpk"] and not s["extra"]:
        raise ValueError("Wybierz odbiorcę: GPK lub podaj własny adres")
    s["subject"] = str(new.get("subject") or DEFAULTS["subject"]).strip()[:120]
    s["address"] = str(new.get("address") or "").strip()[:120]
    s["intro"] = str(new.get("intro") or DEFAULTS["intro"]).strip()[:200]
    s["sanity"] = bool(new.get("sanity", True))
    allv = meters._read_all()
    allv["readings"] = s
    meters._write_all(allv)
    return s


def recipients(s: dict, user: str) -> tuple[list[str], list[str]]:
    """(do, kopia): GPK jeśli wybrano; własne adresy: jako Do, gdy GPK wyłączone, inaczej jako kopia."""
    extra = emails(s.get("extra", ""))
    if s.get("cc_self") and user and user not in extra:
        extra.append(user)
    if s.get("to_gpk", True):
        return [GPK_ADDR], extra
    return extra, []


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(getattr(meters, "TZ_NAME", None) or os.environ.get("TZ") or "Europe/Warsaw")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Europe/Warsaw")


def month_key(d: datetime) -> str:
    return f"{d.year}-{d.month:02d}"


def target(now: datetime, s: dict) -> datetime:
    hh, mm = map(int, s["time"].split(":"))
    return now.replace(day=int(s["day"]), hour=hh, minute=mm, second=0, microsecond=0)


def fmt(v: float) -> str:
    """Jedno miejsce po przecinku, np. 1647.8"""
    return f"{v:.1f}"


def read_values(m: dict) -> dict:
    res = ha_out.ws_batch([{"type": "get_states"}])
    if res is None:
        raise Unavailable("brak połączenia z HA: " + (ha_out.LAST_WS_ERROR or "nieznany powód"))
    states = {x["entity_id"]: x for x in (res[0] or [])}
    out = {}
    for key in ("main", "sub"):
        eid = m.get(key)
        if not eid:
            continue
        st = states.get(eid)
        if not st:
            raise Unavailable(f"encja {eid} nie istnieje w HA")
        try:
            v = float(st["state"])
        except (TypeError, ValueError):
            raise Unavailable(f"encja {eid} ma stan „{st.get('state')}”") from None
        out[key] = round(meters._m3(v, (st.get("attributes") or {}).get("unit_of_measurement")), 3)
    if "main" not in out:
        raise Unavailable("nie wybrano licznika głównego (zakładka Liczniki)")
    return out


def check_sanity(store, vals: dict):
    prev = next((r for r in store.submissions() if r["status"] == "sent" and r["main"]), None)
    if prev and vals["main"] < float(prev["main"]) - 0.001:
        raise SanityError(f"odczyt głównego {fmt(vals['main'])} jest mniejszy niż ostatnio wysłany {prev['main']}")
    if prev and vals.get("sub") is not None and prev["sub"] and vals["sub"] < float(prev["sub"]) - 0.001:
        raise SanityError(f"odczyt ogrodu {fmt(vals['sub'])} jest mniejszy niż ostatnio wysłany {prev['sub']}")
    inv = store.invoices()
    if inv and inv[-1].get("main_cur") and vals["main"] < inv[-1]["main_cur"] - 0.5:
        raise SanityError(f"odczyt głównego {fmt(vals['main'])} jest mniejszy niż na ostatniej fakturze ({inv[-1]['main_cur']:g})")


def compose(now: datetime, vals: dict, s: dict) -> tuple[str, str]:
    lines = [f"{s['intro']} {now.strftime('%d-%m-%Y')}", "", f"Licznik wody główny: {fmt(vals['main'])} m³"]
    if vals.get("sub") is not None:
        lines.append(f"Licznik wody ogród: {fmt(vals['sub'])} m³")
    subj = f"{s['subject']} {s['address']}".strip() if s.get("address") else s["subject"]
    return subj, "\n".join(lines) + "\n"


def preview(store, user: str = "", now: datetime | None = None) -> dict:
    now = now or datetime.now(tz())
    s = get_settings()
    try:
        vals = read_values(meters.load_settings())
    except Unavailable as e:
        return dict(ok=False, error=str(e))
    subj, body = compose(now, vals, s)
    to, cc = recipients(s, user)
    out = dict(ok=True, subject=subj, body=body, values=vals, to=to, cc=cc)
    try:
        check_sanity(store, vals)
    except SanityError as e:
        out["warning"] = str(e)
    return out


def _deliver(store, o: dict, sid: int, kind: str, now: datetime, force: bool) -> None:
    s, month = get_settings(), month_key(now)
    vals = read_values(meters.load_settings())
    if s["sanity"] and not force:
        check_sanity(store, vals)
    user, pw = o["gmail_user"], o["gmail_app_password"]
    to, cc = recipients(s, user)
    if kind == "auto":
        try:
            if mailer.already_sent(user, pw, month):
                store.update_submission(sid, status="sent", sent_at=now.isoformat(timespec="seconds"), main=fmt(vals["main"]),
                                        sub=fmt(vals["sub"]) if vals.get("sub") is not None else None, to_addr=", ".join(to),
                                        error="mail za ten miesiąc już istniał w Gmailu (wysłany przed awarią)")
                return
        except Exception as e:  # noqa: BLE001  - brak sprawdzenia nie blokuje wysyłki
            log.warning("nie udało się sprawdzić, czy mail już wyszedł: %s", e)
    subj, body = compose(now, vals, s)
    mailer.send_mail(user, pw, to, cc, subj, body, month)
    store.update_submission(sid, status="sent", sent_at=now.isoformat(timespec="seconds"), main=fmt(vals["main"]),
                            sub=fmt(vals["sub"]) if vals.get("sub") is not None else None, to_addr=", ".join(to), error=None)
    notifications.emit(store, "readings_sent", "Wysłano stany liczników", f"{body}Do: {', '.join(to + cc)}",
                       f"rd:sent:{sid}", now)


def _attempt(store, o, sid, kind, now, force=False) -> str:
    rec = next(r for r in store.submissions() if r["id"] == sid)
    store.update_submission(sid, attempts=(rec["attempts"] or 0) + 1, last_try=time.time())
    s = get_settings()
    try:
        _deliver(store, o, sid, kind, now, force)
        return "sent"
    except (Unavailable, SanityError) as e:
        err, level = str(e), type(e).__name__
    except Exception as e:  # noqa: BLE001
        err, level = f"{type(e).__name__}: {e}", "Error"
    rec = next(r for r in store.submissions() if r["id"] == sid)
    store.update_submission(sid, status="failed", error=err)
    log.warning("wysyłka odczytów nieudana (%s, próba %s): %s", level, rec["attempts"], err)
    if not rec["notified"] and (level == "SanityError" or rec["attempts"] >= 3):
        notifications.emit(store, "readings_failed", "Stany liczników nie zostały wysłane",
                           f"Dodatek próbuje ponownie co 10 minut. Powód: {err}", f"rd:fail:{sid}", now)
        store.update_submission(sid, notified=1)
    return "failed"


def tick(store, o: dict, now: datetime | None = None) -> str:
    """Wywoływane co minutę (i przy starcie). Zwraca stan: disabled/wait/done/backoff/sent/failed/missed."""
    s = get_settings()
    if not s["enabled"]:
        return "disabled"
    now = now or datetime.now(tz())
    month = month_key(now)
    recs = [r for r in store.submissions(month) if r["kind"] == "auto"]
    if any(r["status"] == "sent" for r in recs):
        return "done"
    if any(r["status"] == "missed" for r in recs):
        return "missed"
    t = target(now, s)
    if now < t:
        return "wait"
    if now > t + timedelta(days=s["window_days"]):
        store.add_submission(month, "auto", "missed", now.isoformat(timespec="seconds"),
                             error=f"nie udało się wysłać w ciągu {s['window_days']} dni")
        if len(store.submissions()) <= 1:  # pierwsze włączenie w środku miesiąca - bez alarmu
            return "missed"
        notifications.emit(store, "readings_failed", "Stany liczników nie zostały wysłane",
                           f"Minęło {s['window_days']} dni od terminu ({t.strftime('%d.%m')}) i odczyty za {month} nie wyszły. "
                           "Wyślij je ręcznie w panelu (zakładka Odczyty).", f"rd:missed:{month}", now)
        return "missed"
    pend = next((r for r in recs if r["status"] in ("pending", "failed")), None)
    if pend and pend["last_try"] and time.time() - pend["last_try"] < RETRY_S:
        return "backoff"
    sid = pend["id"] if pend else store.add_submission(month, "auto", "pending", now.isoformat(timespec="seconds"))
    return _attempt(store, o, sid, "auto", now)


def send_manual(store, o: dict, force: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz())
    sid = store.add_submission(month_key(now), "manual", "pending", now.isoformat(timespec="seconds"))
    r = _attempt(store, o, sid, "manual", now, force)
    rec = next(x for x in store.submissions() if x["id"] == sid)
    return dict(result=r, record=rec)


def status(store, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz())
    s = get_settings()
    month = month_key(now)
    recs = store.submissions(month)
    auto_sent = any(r["status"] == "sent" for r in recs)
    t = target(now, s)
    if auto_sent or now > t + timedelta(days=s["window_days"]):
        nxt = target((now.replace(day=1) + timedelta(days=32)).replace(day=1), s)
    else:
        nxt = t
    return dict(settings=s, month=month, sent_this_month=auto_sent, next_due=nxt.isoformat(timespec="minutes"),
                history=store.submissions()[:36])
