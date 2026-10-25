"""Wyliczanie wartości sensorów z listy faktur."""
from datetime import date, timedelta


def _gross_price(net: float | None, vat: int) -> float | None:
    return None if net is None else round(net * (1 + vat / 100), 4)


def compute(invoices: list[dict]) -> dict:
    if not invoices:
        return {}
    last = invoices[-1]
    vat = last["vat_rate"]
    wp, sp = _gross_price(last["water_price_net"], vat), _gross_price(last["sewage_price_net"], vat)
    days = max(last["period_days"], 1)

    # koszt na dobę z każdej faktury (brutto faktury / dni okresu), uśredniony z ostatnich 12 miesięcy
    cutoff = (date.today() - timedelta(days=365)).isoformat()
    recent = [i for i in invoices if i["period_end"] >= cutoff and i["period_days"] > 0]
    if recent:
        tot_cost = sum(i["invoice_gross"] for i in recent)
        tot_days = sum(i["period_days"] for i in recent)
        monthly_avg = round(tot_cost / tot_days * 30.4375, 2)
        home_m3 = sum(i["water_home_m3"] for i in recent)
        year_m3_home = round(home_m3 / tot_days * 365, 1)
    else:
        monthly_avg, year_m3_home = None, None

    home_cost = last["gross_water_home"] + last["gross_sewage"]
    home_m3 = last["water_home_m3"]
    return dict(
        last_invoice_gross=last["invoice_gross"],
        last_payable=last["payable"],
        last_number=last["number"],
        last_issue_date=last["issue_date"],
        last_due_date=last["due_date"],
        last_period_days=last["period_days"],
        last_home_m3=home_m3,
        last_garden_m3=last["water_garden_m3"],
        last_sewage_m3=last["sewage_m3"],
        water_price_gross=wp,
        sewage_price_gross=sp,
        abo_price_gross=_gross_price(last["abo_price_net"], vat),
        # realny koszt 1 m3 wody domowej: woda + ścieki + abonament rozłożony na zużycie
        home_cost_per_m3=round((home_cost + last["gross_abo"]) / home_m3, 2) if home_m3 else None,
        garden_cost_per_m3=round(last["gross_water_garden"] / last["water_garden_m3"], 2) if last["water_garden_m3"] else None,
        home_cost_last=round(home_cost, 2),
        garden_cost_last=last["gross_water_garden"],
        daily_cost_last=round(last["invoice_gross"] / days, 2),
        monthly_avg_12m=monthly_avg,
        year_m3_home=year_m3_home,
        interest_last=last["interest_amount"],
        invoice_count=len(invoices),
    )
