"""Money arithmetic (rule 7). Pure functions on integer minor units; nothing here touches the
database, so every calculation is tested on its own.

- A line: net = quantity × unit price − discount. Each tax part is net × rate, rounded half up
  to a whole minor unit, per line. Line total = net + its tax parts.
- An invoice: subtotal = Σ net, tax = Σ line tax, total = subtotal + tax.
- Installments add up to the total exactly; an equal split gives the extra minor units to the
  first installments (₹10,000 in 3 = 3,333.34 + 3,333.33 + 3,333.33).
- A payment is applied to the oldest unpaid installment first and never beyond the balance.
"""

from dataclasses import dataclass, field
from datetime import date

from app.core.errors import Invalid
from app.core.money import check_amount, line_total

MAX_RATE_BP = 10_000  # 100%
MAX_INSTALLMENTS = 60


def half_up(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded half up, for numerator >= 0, denominator > 0."""
    return (numerator * 2 + denominator) // (denominator * 2)


def check_parts(parts: list[dict]) -> list[dict]:
    """A tax rate's parts: [{"name": "CGST", "rate_bp": 900}]; 0–100% each and in total."""
    out = []
    for p in parts:
        name = str(p.get("name", "")).strip()[:40]
        rate = p.get("rate_bp")
        if not name:
            raise Invalid("Every tax part needs a name")
        if not isinstance(rate, int) or isinstance(rate, bool) or not 0 <= rate <= MAX_RATE_BP:
            raise Invalid("A tax rate must be between 0% and 100%")
        out.append({"name": name, "rate_bp": rate})
    if sum(p["rate_bp"] for p in out) > MAX_RATE_BP:
        raise Invalid("The tax parts add up to more than 100%")
    return out


@dataclass(frozen=True)
class Line:
    net: int
    tax: int
    total: int
    parts: list[dict]  # [{"name", "rate_bp", "amount"}]


def line(quantity: int, unit_price: int, discount: int, parts: list[dict]) -> Line:
    net = line_total(quantity, unit_price, discount)
    amounts = [p | {"amount": half_up(net * p["rate_bp"], MAX_RATE_BP)} for p in parts]
    tax = sum(a["amount"] for a in amounts)
    return Line(net=net, tax=tax, total=check_amount(net + tax, "Line total"), parts=amounts)


@dataclass(frozen=True)
class Totals:
    subtotal: int
    discount: int
    tax: int
    total: int
    breakdown: list[dict] = field(default_factory=list)  # [{"name", "rate_bp", "amount"}]


def totals(lines: list[tuple[Line, int]]) -> Totals:
    """lines = [(computed line, its discount)]. Tax parts with the same name and rate are
    shown once on the invoice, added up."""
    breakdown: dict[tuple[str, int], int] = {}
    for ln, _ in lines:
        for p in ln.parts:
            key = (p["name"], p["rate_bp"])
            breakdown[key] = breakdown.get(key, 0) + p["amount"]
    subtotal = sum(ln.net for ln, _ in lines)
    tax = sum(ln.tax for ln, _ in lines)
    return Totals(
        subtotal=subtotal,
        discount=sum(d for _, d in lines),
        tax=tax,
        total=check_amount(subtotal + tax, "Invoice total"),
        breakdown=[{"name": n, "rate_bp": r, "amount": a} for (n, r), a in breakdown.items()],
    )


def split_equal(total: int, count: int) -> list[int]:
    if not 1 <= count <= MAX_INSTALLMENTS:
        raise Invalid(f"Choose between 1 and {MAX_INSTALLMENTS} installments")
    if total < count:
        raise Invalid("The amount is too small to split that many times")
    base, extra = divmod(total, count)
    return [base + (1 if i < extra else 0) for i in range(count)]


def check_schedule(total: int, plan: list[tuple[int, date]], issue_date: date | None) -> None:
    """Installments: each more than zero, dates in order, adding up to the total exactly."""
    if not 1 <= len(plan) <= MAX_INSTALLMENTS:
        raise Invalid(f"Choose between 1 and {MAX_INSTALLMENTS} installments")
    for amount, _ in plan:
        check_amount(amount, "Installment")
        if amount == 0:
            raise Invalid("Every installment must be more than zero")
    dates = [d for _, d in plan]
    if dates != sorted(dates):
        raise Invalid("Put the installments in date order")
    if issue_date and dates[0] < issue_date:
        raise Invalid("An installment cannot be due before the invoice date")
    if sum(a for a, _ in plan) != total:
        raise Invalid("The installments must add up to the invoice total exactly")


def allocate(amount: int, open_items: list[tuple[object, int, int]]) -> list[tuple[object, int]]:
    """Apply a payment oldest first. open_items = [(key, amount, paid)] in due order.
    Refuses anything above what is still due (no overpayments, Decision log #34 M5)."""
    check_amount(amount, "Payment")
    if amount == 0:
        raise Invalid("The payment must be more than zero")
    due = sum(a - p for _, a, p in open_items)
    if amount > due:
        raise Invalid("The payment is more than what is still due")
    out, left = [], amount
    for key, a, p in open_items:
        if left == 0:
            break
        part = min(a - p, left)
        if part > 0:
            out.append((key, part))
            left -= part
    return out


AGING = ("0-30", "31-60", "61-90", "90+")


def aging_bucket(days_overdue: int) -> str:
    if days_overdue <= 30:
        return AGING[0]
    if days_overdue <= 60:
        return AGING[1]
    if days_overdue <= 90:
        return AGING[2]
    return AGING[3]


def period(day: date, start_month: int) -> str:
    """The financial year a date falls in: '2026-27' (April start) or '2026' (January)."""
    if start_month == 1:
        return f"{day.year}"
    first = day.year if day.month >= start_month else day.year - 1
    return f"{first}-{(first + 1) % 100:02d}"


def add_months(day: date, months: int) -> date:
    """Same day of the month, months later; the 31st becomes the month's last day."""
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    raise AssertionError("unreachable")
