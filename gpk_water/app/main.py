import json
import logging
import os
import sys
import time

from . import ha_out, mailbox, metrics, web
from .db import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gpk")

OPTS = "/data/options.json"


def load_opts() -> dict:
    with open(OPTS) as f:
        return json.load(f)


def run_once(o: dict, store: Store):
    st = mailbox.sync(store, o["imap_host"], o["gmail_user"], o["gmail_app_password"],
                      o["sender"], o["since"])
    log.info("mail: %s", st)
    invoices = store.invoices()
    if not invoices:
        log.warning("brak faktur w bazie")
        return
    values = metrics.compute(invoices)
    ha_out.publish(o["mqtt_host"], int(o["mqtt_port"]), o.get("mqtt_user") or None, o.get("mqtt_password") or None, values)
    if st["new"] or o.get("force_history_import"):
        ha_out.import_history(invoices)
    failed = store.db.execute("SELECT uid, note FROM seen_mail WHERE status='failed'").fetchall()
    if failed:
        log.warning("%d maili z PDF nie sparsowano (nowy format?): %s", len(failed), failed[:5])


def main():
    o = load_opts()
    os.makedirs("/data", exist_ok=True)
    store = Store("/data/invoices.db")
    web.start(store)
    interval = max(int(o.get("check_hours", 6)), 1) * 3600
    first = True
    while True:
        try:
            if first and o.get("force_history_import"):
                log.info("pierwsze uruchomienie: pełny import historii")
            run_once(o, store)
        except Exception:  # noqa: BLE001
            log.exception("cykl nieudany, spróbuję ponownie za %d h", interval // 3600)
        first = False
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
