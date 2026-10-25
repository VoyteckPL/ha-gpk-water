"""Panel (ingress) w pasku bocznym HA: dane JSON dla interfejsu, pliki statyczne, PDF-y, CSV."""
import csv
import io
import json
import mimetypes
import os
import threading
import time
import zipfile
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from . import readings, energy, notifications

from . import ha_out, meters, state
from .db import pdf_path
from .mailbox import FAILED_DIR

STATIC = os.path.join(os.path.dirname(__file__), "static")
CSV_COLS = ["number", "issue_date", "due_date", "period_start", "period_end", "period_days", "main_usage",
            "sub_usage", "water_home_m3", "water_garden_m3", "sewage_m3", "water_price_net", "sewage_price_net",
            "abo_price_net", "vat_rate", "gross_water_home", "gross_water_garden", "gross_sewage", "gross_abo",
            "gross_other", "net_total", "vat_total", "invoice_gross", "interest_amount", "payable"]

_ent_cache = {"t": 0, "data": {}}


def _entities() -> list[dict]:
    if time.time() - _ent_cache["t"] > 30:
        _ent_cache.update(t=time.time(), data=ha_out.fetch_ha_entities())
    live, pub = _ent_cache["data"], dict(state.snapshot().get("published") or {})
    pub.update((state.snapshot().get("est_values") or {}))
    rows = []
    for key, name, unit, dclass, sclass, icon in ha_out.SENSORS + ha_out.SENSORS_EST:
        uid = f"gpk_water_{key}"
        lv = live.get(uid, {})
        rows.append(dict(kind="sensor", unique_id=uid, name=name, unit=unit, device_class=dclass, icon=icon,
                         topic=f"gpk_water/{key}", entity_id=lv.get("entity_id"), ha_state=lv.get("state"),
                         last_updated=lv.get("last_updated"), in_ha=bool(lv), value=pub.get(key)))
    for sid, name, unit, _ in ha_out.STAT_SERIES:
        rows.append(dict(kind="statistic", unique_id=sid, name=name, unit=unit, entity_id=sid, in_ha=None))
    return rows


class Handler(BaseHTTPRequestHandler):
    def __init__(self, store, opts, *a, **k):
        self.store, self.opts = store, opts
        super().__init__(*a, **k)

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = unquote(self.path.split("?")[0]).strip("/")
        try:
            return self._route(path)
        except Exception as e:  # noqa: BLE001
            self._send(500, f"błąd: {e}".encode(), "text/plain; charset=utf-8")

    def do_POST(self):
        path = unquote(self.path.split("?")[0]).strip("/")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if path == "api/meters/settings":
                main, sub = (body.get("main") or "").strip(), (body.get("sub") or "").strip()
                if sub and sub == main:
                    return self._send(400, "Licznik główny i ogrodowy muszą być różne".encode(), "text/plain; charset=utf-8")
                meters.save_settings(main or None, sub or None)
                return self._json(meters.refresh(self.store, force=True))
            if path == "api/readings/settings":
                try:
                    readings.save_settings(body)
                except ValueError as e:
                    return self._send(400, str(e).encode(), "text/plain; charset=utf-8")
                return self._json(readings.status(self.store))
            if path == "api/readings/send":
                return self._json(readings.send_manual(self.store, self.opts, bool(body.get("force"))))
            if path == "api/notifications/settings":
                try:
                    return self._json(notifications.save_settings(body))
                except ValueError as e:
                    return self._send(400, str(e).encode(), "text/plain; charset=utf-8")
            if path == "api/notifications/test":
                return self._json(notifications.test(self.store, body.get("notify_services")))
            if path == "api/energy/rebuild":
                return self._json(energy.import_all(self.store))
            self._send(404, b"", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._send(500, f"błąd: {e}".encode(), "text/plain; charset=utf-8")

    def _route(self, path):
        if path in ("", "index.html"):
            return self._send(200, open(os.path.join(STATIC, "index.html"), "rb").read())
        if path.startswith("static/"):
            fp = os.path.join(STATIC, os.path.basename(path))
            if os.path.isfile(fp):
                ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
                return self._send(200, open(fp, "rb").read(), ctype, {"Cache-Control": "max-age=3600"})
            return self._send(404, b"", "text/plain")
        if path == "api/data":
            st = state.snapshot()
            invs = self.store.invoices()
            for i in invs:
                i["has_pdf"] = os.path.exists(pdf_path(i["number"]))
            st["published"] = st.get("published") or {}
            from . import notify as _nt
            op = _nt.OPEN_TAB["pending"]
            _nt.OPEN_TAB["pending"] = False
            return self._json(dict(version=state.version(), now=time.time(), invoices=invs, status=st, open_tab="nt" if op else None,
                                   failed_files=sorted(os.listdir(FAILED_DIR)) if os.path.isdir(FAILED_DIR) else [],
                                   sender=self.opts.get("sender"), since=self.opts.get("since")))
        if path == "api/readings":
            return self._json(readings.status(self.store))
        if path == "api/readings/preview":
            return self._json(readings.preview(self.store, self.opts.get("gmail_user", "")))
        if path == "api/notifications/services":
            return self._json(notifications.list_services())
        if path == "api/notifications":
            return self._json(dict(settings=notifications.get_settings(), log=self.store.notifications(),
                                   events={k: dict(name=v[0], desc=v[1], params=list(v[3])) for k, v in notifications.EVENTS.items()}))
        if path == "api/energy":
            return self._json(energy.LAST)
        if path == "api/meters":
            return self._json(meters.refresh(self.store))
        if path == "api/meters/candidates":
            return self._json(meters.candidates())
        if path == "api/entities":
            return self._json(_entities())
        if path.startswith("api/pdf/"):
            fp = pdf_path(path[8:])
            if os.path.isfile(fp):
                name = os.path.basename(fp)
                return self._send(200, open(fp, "rb").read(), "application/pdf",
                                  {"Content-Disposition": f'inline; filename="faktura_{name}"'})
            return self._send(404, "brak PDF".encode(), "text/plain; charset=utf-8")
        if path == "api/invoices.csv":
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            w.writerow(CSV_COLS)
            for i in self.store.invoices():
                w.writerow([str(i.get(c, "")).replace(".", ",") if isinstance(i.get(c), float) else i.get(c, "")
                            for c in CSV_COLS])
            return self._send(200, ("﻿" + buf.getvalue()).encode(), "text/csv; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="faktury_woda.csv"'})
        if path == "failed.zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for n in (sorted(os.listdir(FAILED_DIR)) if os.path.isdir(FAILED_DIR) else []):
                    z.write(os.path.join(FAILED_DIR, n), n)
            return self._send(200, buf.getvalue(), "application/zip",
                              {"Content-Disposition": 'attachment; filename="gpk_nieodczytane.zip"'})
        if path.startswith("failed/"):
            name = os.path.basename(path[7:])
            fp = os.path.join(FAILED_DIR, name)
            if os.path.isfile(fp):
                return self._send(200, open(fp, "rb").read(), "application/pdf",
                                  {"Content-Disposition": f'attachment; filename="{name}"'})
        self._send(404, b"nie ma", "text/plain")


def start(store, opts=None, port=8099):
    srv = ThreadingHTTPServer(("0.0.0.0", port), partial(Handler, store, opts or {}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
