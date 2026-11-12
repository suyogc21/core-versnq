"""Every money calculation (rule 7): whole minor units, no floats, sums that always match."""

from datetime import date

import pytest

from app.core.errors import Invalid
from app.core.money import display, plain
from app.modules.money import calc

GST18 = [{"name": "CGST", "rate_bp": 900}, {"name": "SGST", "rate_bp": 900}]


def test_line_net_tax_and_total():
    ln = calc.line(2, 1_000_000, 50_000, GST18)  # 2 × ₹10,000 − ₹500
    assert ln.net == 1_950_000
    assert [p["amount"] for p in ln.parts] == [175_500, 175_500]
    assert ln.tax == 351_000 and ln.total == 2_301_000


def test_tax_rounds_half_up_per_part():
    # 9% of 105 paise = 9.45 -> 9; of 150 = 13.5 -> 14
    assert calc.line(1, 105, 0, GST18).parts[0]["amount"] == 9
    assert calc.line(1, 150, 0, GST18).parts[0]["amount"] == 14
    assert calc.half_up(5, 10) == 1 and calc.half_up(4, 10) == 0 and calc.half_up(0, 7) == 0


def test_no_tax_and_zero_price():
    ln = calc.line(3, 0, 0, [])
    assert (ln.net, ln.tax, ln.total) == (0, 0, 0)


def test_discount_cannot_exceed_the_line():
    with pytest.raises(Invalid):
        calc.line(1, 100, 101, [])


def test_invoice_totals_and_breakdown_add_up():
    a = calc.line(1, 999_999, 0, GST18)
    b = calc.line(3, 333_333, 1, GST18)
    c = calc.line(1, 50_000, 0, [{"name": "IGST", "rate_bp": 1800}])
    t = calc.totals([(a, 0), (b, 1), (c, 0)])
    assert t.subtotal == a.net + b.net + c.net
    assert t.tax == a.tax + b.tax + c.tax == sum(x["amount"] for x in t.breakdown)
    assert t.total == t.subtotal + t.tax
    assert t.discount == 1
    assert {(x["name"], x["rate_bp"]) for x in t.breakdown} == {
        ("CGST", 900),
        ("SGST", 900),
        ("IGST", 1800),
    }


def test_tax_parts_checked():
    assert calc.check_parts([{"name": " VAT ", "rate_bp": 500}]) == [
        {"name": "VAT", "rate_bp": 500}
    ]
    for bad in (
        [{"name": "", "rate_bp": 5}],
        [{"name": "X", "rate_bp": -1}],
        [{"name": "X", "rate_bp": 10_001}],
        [{"name": "X", "rate_bp": 1.5}],
        [{"name": "A", "rate_bp": 6000}, {"name": "B", "rate_bp": 5000}],
    ):
        with pytest.raises(Invalid):
            calc.check_parts(bad)


def test_equal_split_gives_the_extra_to_the_first():
    assert calc.split_equal(1_000_000, 3) == [333_334, 333_333, 333_333]  # ₹10,000 in 3
    assert calc.split_equal(1_000_001, 3) == [333_334, 333_334, 333_333]
    assert sum(calc.split_equal(7, 7)) == 7
    with pytest.raises(Invalid):
        calc.split_equal(2, 3)
    with pytest.raises(Invalid):
        calc.split_equal(100, 0)


def test_schedule_must_add_up_and_be_in_order():
    d1, d2 = date(2026, 12, 1), date(2027, 1, 1)
    calc.check_schedule(100, [(60, d1), (40, d2)], date(2026, 11, 12))
    for plan in ([(60, d1), (41, d2)], [(60, d2), (40, d1)], [(100, d1), (0, d2)]):
        with pytest.raises(Invalid):
            calc.check_schedule(100, plan, None)
    with pytest.raises(Invalid):  # due before the invoice date
        calc.check_schedule(100, [(100, date(2026, 1, 1))], date(2026, 11, 12))


def test_allocation_oldest_first_and_never_beyond_the_balance():
    items = [("a", 300, 300), ("b", 300, 100), ("c", 400, 0)]
    assert calc.allocate(250, items) == [("b", 200), ("c", 50)]
    assert calc.allocate(600, items) == [("b", 200), ("c", 400)]
    with pytest.raises(Invalid):
        calc.allocate(601, items)
    with pytest.raises(Invalid):
        calc.allocate(0, items)


def test_aging_buckets():
    assert [calc.aging_bucket(d) for d in (1, 30, 31, 60, 61, 90, 91, 400)] == [
        "0-30",
        "0-30",
        "31-60",
        "31-60",
        "61-90",
        "61-90",
        "90+",
        "90+",
    ]


def test_financial_year_and_months():
    assert calc.period(date(2026, 4, 1), 4) == "2026-27"
    assert calc.period(date(2027, 3, 31), 4) == "2026-27"
    assert calc.period(date(2099, 12, 1), 4) == "2099-00"
    assert calc.period(date(2026, 3, 1), 1) == "2026"
    assert calc.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert calc.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert calc.add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert calc.add_months(date(2026, 8, 31), 1) == date(2026, 9, 30)


def test_currencies_with_0_2_and_3_decimals():
    assert plain(333_334, "INR") == "3333.34" and display(333_334, "INR") == "INR 3,333.34"
    assert plain(5000, "JPY") == "5000" and display(1_234_567, "JPY") == "JPY 1,234,567"
    assert plain(1_234_567, "KWD") == "1234.567" and display(5, "KWD") == "KWD 0.005"
    assert calc.split_equal(10, 3) == [4, 3, 3]  # 10 yen in 3: still exact
