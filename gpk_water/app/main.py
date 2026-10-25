import json
import logging
import os
import sys
import time

from . import ha_out, mailbox, metrics, state, web
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
    mailbox.cleanup_failed(store)
    state.update(mail_stats=st, failed_mails=store.failed_mails())
    invoices = store.invoices()
    if not invoices:
        log.warning("brak faktur w bazie")
        return
    values = metrics.compute(invoices)
    try:
        ha_out.publish(o["mqtt_host"], int(o["mqtt_port"]), o.get("mqtt_user") or None, o.get("mqtt_password") or None, values)
        state.update(mqtt_ok=True, published=values)
    except Exception as e:  # noqa: BLE001
        state.update(mqtt_ok=False)
        log.error("MQTT: %s", e)
        raise
    if st["new"] or o.get("force_history_import"):
        ha_out.import_history(invoices)
        state.update(history_imported=time.time())
    failed = store.db.execute("SELECT uid, note FROM seen_mail WHERE status='failed'").fetchall()
    if failed:
        log.warning("%d maili z PDF nie sparsowano (nowy format?): %s", len(failed), failed[:5])


def main():
    o = load_opts()
    os.makedirs("/data", exist_ok=True)
    store = Store("/data/invoices.db")
    web.start(store, o)
    interval = max(int(o.get("check_hours", 6)), 1) * 3600
    first = True
    while True:
        try:
            if first and o.get("force_history_import"):
                log.info("pierwsze uruchomienie: pełny import historii")
            state.update(last_run=time.time(), interval_h=interval // 3600)
            run_once(o, store)
            state.update(last_ok=time.time(), last_error=None)
        except Exception as e:  # noqa: BLE001
            state.update(last_error=f"{type(e).__name__}: {e}")
            log.exception("cykl nieudany, spróbuję ponownie za %d h", interval // 3600)
        first = False
        state.update(next_run=time.time() + interval)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
