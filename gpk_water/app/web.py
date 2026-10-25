"""Panel (ingress) w pasku bocznym HA: lista faktur i pobieranie nieudanych PDF-ów."""
import html
import os
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote

from .mailbox import FAILED_DIR

STYLE = ("body{font:16px system-ui;margin:16px;max-width:800px}table{border-collapse:collapse;width:100%}"
         "td,th{padding:6px 8px;border-bottom:1px solid #8884;text-align:left}a{color:#03a9f4}"
         "@media(prefers-color-scheme:dark){body{background:#111;color:#eee}}")


class Handler(BaseHTTPRequestHandler):
    def __init__(self, store, *a, **k):
        self.store = store
        super().__init__(*a, **k)

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(self.path.split("?")[0]).strip("/")
        if path.startswith("failed/"):
            name = os.path.basename(path[7:])
            fp = os.path.join(FAILED_DIR, name)
            if os.path.isfile(fp):
                return self._send(200, open(fp, "rb").read(), "application/pdf",
                                  {"Content-Disposition": f'attachment; filename="{name}"'})
            return self._send(404, b"nie ma pliku", "text/plain")
        failed = sorted(os.listdir(FAILED_DIR)) if os.path.isdir(FAILED_DIR) else []
        rows = "".join(
            f"<tr><td>{html.escape(i['number'])}</td><td>{i['issue_date']}</td><td>{i['invoice_gross']:.2f}</td>"
            f"<td>{i['water_home_m3']:g}+{i['water_garden_m3']:g}</td></tr>"
            for i in reversed(self.store.invoices()))
        links = "".join(f'<li><a href="failed/{quote(n)}">{html.escape(n)}</a></li>' for n in failed) or "<li>brak</li>"
        page = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                f"<style>{STYLE}</style><h2>Faktury za wodę</h2><h3>Nieodczytane PDF-y (do wysłania Claude'owi)</h3>"
                f"<ul>{links}</ul><h3>Sparsowane faktury</h3><table><tr><th>Nr</th><th>Data</th><th>Brutto zł</th>"
                f"<th>m³ dom+ogród</th></tr>{rows}</table>")
        self._send(200, page.encode())


def start(store, port=8099):
    srv = ThreadingHTTPServer(("0.0.0.0", port), partial(Handler, store))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
