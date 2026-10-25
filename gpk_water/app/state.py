"""Stan działania add-onu, pokazywany w panelu."""
import re
import threading
import time

lock = threading.Lock()
STATE = dict(
    started=time.time(), last_run=None, last_ok=None, last_error=None, next_run=None,
    mail_stats=None, mqtt_ok=None, history_imported=None, interval_h=None,
    published=None, failed_mails=[],
)


def update(**kw):
    with lock:
        STATE.update(kw)


def snapshot() -> dict:
    with lock:
        return dict(STATE)


def version() -> str:
    for p in ("/opt/gpk_water/config.yaml", "config.yaml", "../config.yaml"):
        try:
            m = re.search(r'^version:\s*"?([\w.\-]+)"?', open(p, encoding="utf-8").read(), re.M)
            if m:
                return m.group(1)
        except OSError:
            pass
    return "?"
