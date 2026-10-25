"""Parser faktur GPK Szemud (tekst z `pdftotext -layout`).

Obsługuje oba znane układy: 2020 (daty dd.mm.rrrr, faktury dwumiesięczne)
i 2026 (daty rrrr-mm-dd, faktury miesięczne, nota odsetkowa na drugiej stronie).
Gdy faktura ma nieznany układ, rzuca ParseError z czytelnym powodem.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from datetime import date, datetime
from decimal import Decimal

NUM = r"-?\d+(?:\s\d{3})*,\d{2}"
DATE = r"(?:\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})"

ITEM_RE = re.compile(
    rf"^\s*(?P<name>[^\d\s].*?)\s+(?P<pkwiu>\d{{2}}\.\d{{2}}\.\d{{2}}(?:\.\d)?)\s+"
    rf"(?P<qty>\d+(?:,\d+)?)\s+(?P<unit>m3|mc)\s+(?P<price>{NUM})\s+(?P<net>{NUM})\s+"
    rf"(?P<vat>\d+)%\s+(?P<vatv>{NUM})\s+(?P<gross>{NUM})\s*$",
    re.M,
)
METER_RE = re.compile(
    rf"^\s*(?P<type>Główny|Podlicznik)\s+(?P<serial>\S+)\s+(?P<d0>{DATE})\s+(?P<r0>\d+(?:,\d+)?)\s+"
    rf"(?P<d1>{DATE})\s+(?P<r1>\d+(?:,\d+)?)(?:\s*\([^)]*\))?\s+(?P<use>\d+(?:,\d+)?)\s*$",
    re.M,
)
TOTALS_RE = re.compile(rf"^\s+(?P<net>{NUM})\s+(?P<vat>{NUM})\s+(?P<gross>{NUM})\s*$", re.M)


class ParseError(Exception):
    pass


def _money(s: str) -> Decimal:
    return Decimal(re.sub(r"\s", "", s).replace(",", "."))


def _qty(s: str) -> Decimal:
    return Decimal(s.replace(",", "."))


def _iso(s: str) -> str:
    return datetime.strptime(s, "%d.%m.%Y" if "." in s else "%Y-%m-%d").date().isoformat()


def _req(pattern: str, text: str, label: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    if not m:
        raise ParseError(f"nie znaleziono pola: {label}")
    return m.group(1)


def _kind(name: str) -> str:
    n = name.lower()
    if n.startswith("woda"):
        return "water"
    if n.startswith(("ścieki", "scieki")):
        return "sewage"
    if n.startswith("abonament"):
        return "subscription"
    return "other"


def pdf_to_text(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        out = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, check=True, timeout=60)
    return out.stdout.decode("utf-8", "replace")


def _f(x: Decimal | None, nd: int = 2) -> float | None:
    return None if x is None else float(round(x, nd))


def parse_invoice_text(text: str) -> dict:
    number = _req(r"Faktura Nr\s+(\S+)", text, "numer faktury")
    issue = _iso(_req(rf"Data wystawienia\s+({DATE})", text, "data wystawienia"))
    sale = _iso(_req(rf"Data sprzeda[żz]y\s+({DATE})", text, "data sprzedaży"))
    due = _iso(_req(rf"Termin p[łl]atno[śs]ci\s+({DATE})", text, "termin płatności"))
    customer = _req(r"Nabywca\s+(\d+)", text, "numer odbiorcy")

    meters = {}
    for m in METER_RE.finditer(text):
        meters["main" if m["type"] == "Główny" else "sub"] = m
    if "main" not in meters:
        raise ParseError("nie znaleziono wiersza licznika głównego")

    items = []
    last_end = 0
    for m in ITEM_RE.finditer(text):
        name = m["name"].strip()
        items.append(
            dict(
                name=name, kind=_kind(name), qty=_qty(m["qty"]), unit=m["unit"],
                price_net=_money(m["price"]), net=_money(m["net"]), vat_rate=int(m["vat"]),
                vat=_money(m["vatv"]), gross=_money(m["gross"]),
            )
        )
        last_end = m.end()
    if not items:
        raise ParseError("nie znaleziono pozycji faktury")

    tm = TOTALS_RE.search(text, last_end)
    if not tm:
        raise ParseError("nie znaleziono wiersza sum")
    net_total, vat_total, gross_total = _money(tm["net"]), _money(tm["vat"]), _money(tm["gross"])

    cur = re.search(rf"Bieżąca faktura\s*:\s*({NUM})", text)
    invoice_gross = _money(cur.group(1)) if cur else gross_total
    payable = _money(_req(rf"DO ZAPŁATY:\s*({NUM})", text, "do zapłaty", re.I))
    interest = re.search(rf"Nota odsetkowa nr\s+(\S+)\s*:\s*({NUM})", text)

    # okres rozliczeniowy = daty odczytów
    main, sub = meters["main"], meters.get("sub")
    starts = [_iso(m["d0"]) for m in meters.values()]
    ends = [_iso(m["d1"]) for m in meters.values()]
    period_start, period_end = min(starts), max(ends)
    period_days = (date.fromisoformat(period_end) - date.fromisoformat(period_start)).days

    main_use = _qty(main["use"])
    sub_use = _qty(sub["use"]) if sub else Decimal(0)

    # woda: pozycja o ilości = zużycie podlicznika to ogród, reszta dom
    water = [i for i in items if i["kind"] == "water"]
    sewage = [i for i in items if i["kind"] == "sewage"]
    abo = [i for i in items if i["kind"] == "subscription"]
    other = [i for i in items if i["kind"] == "other"]
    warnings: list[str] = []

    garden = []
    if sub_use > 0 and len(water) > 1:
        for i in water:
            if i["qty"] == sub_use:
                garden = [i]
                break
    if sub_use > 0 and not garden:
        warnings.append("nie dopasowano pozycji wody do podlicznika - cała woda policzona jako dom")
    home = [i for i in water if not any(i is g for g in garden)]

    def s(lst, key):
        return sum((i[key] for i in lst), Decimal(0))

    if sum((i["gross"] for i in items), Decimal(0)) != gross_total:
        warnings.append("suma pozycji brutto różni się od sumy na fakturze")
    if cur and invoice_gross != gross_total:
        warnings.append("'Bieżąca faktura' różni się od sumy brutto")
    if _qty(main["r1"]) - _qty(main["r0"]) != main_use:
        warnings.append("zużycie licznika głównego nie zgadza się z odczytami")
    if s(sewage, "qty") != main_use - sub_use:
        warnings.append("ilość ścieków różni się od głównego minus podlicznik")

    vat_rate = items[0]["vat_rate"]
    return dict(
        number=number, customer_id=customer, issue_date=issue, sale_date=sale, due_date=due,
        period_start=period_start, period_end=period_end, period_days=period_days,
        main_serial=main["serial"], sub_serial=sub["serial"] if sub else None,
        main_prev=_f(_qty(main["r0"]), 3), main_cur=_f(_qty(main["r1"]), 3), main_usage=_f(main_use, 3),
        sub_prev=_f(_qty(sub["r0"]), 3) if sub else None, sub_cur=_f(_qty(sub["r1"]), 3) if sub else None,
        sub_usage=_f(sub_use, 3),
        water_home_m3=_f(s(home, "qty"), 3), water_garden_m3=_f(s(garden, "qty"), 3),
        sewage_m3=_f(s(sewage, "qty"), 3),
        water_price_net=_f(water[0]["price_net"]) if water else None,
        sewage_price_net=_f(sewage[0]["price_net"]) if sewage else None,
        abo_price_net=_f(abo[0]["price_net"]) if abo else None,
        abo_months=_f(s(abo, "qty"), 3), vat_rate=vat_rate,
        gross_water_home=_f(s(home, "gross")), gross_water_garden=_f(s(garden, "gross")),
        gross_sewage=_f(s(sewage, "gross")), gross_abo=_f(s(abo, "gross")), gross_other=_f(s(other, "gross")),
        net_total=_f(net_total), vat_total=_f(vat_total), invoice_gross=_f(invoice_gross), payable=_f(payable),
        interest_amount=_f(_money(interest.group(2))) if interest else 0.0,
        interest_note=interest.group(1) if interest else None,
        items=[{k: (float(v) if isinstance(v, Decimal) else v) for k, v in i.items()} for i in items],
        warnings=warnings,
    )


def parse_invoice_pdf(data: bytes) -> dict:
    return parse_invoice_text(pdf_to_text(data))
