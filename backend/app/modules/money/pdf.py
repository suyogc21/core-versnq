"""Invoice and receipt PDFs (reportlab). Made on demand from the database, so they always match
the record and use no storage. The UPI QR is drawn by reportlab's own QR code maker.

Amounts are shown with the currency code ("INR 3,333.34"), never a symbol, so every font works.
"""

from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from urllib.parse import quote
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.money import display, plain

INK = colors.HexColor("#1d1d1f")
MUTED = colors.HexColor("#6e6e73")
LINE = colors.HexColor("#d2d2d7")
_ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_ss["Normal"], fontSize=9, leading=12, textColor=INK)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10, textColor=MUTED)
TITLE = ParagraphStyle("title", parent=BODY, fontSize=18, leading=22, fontName="Helvetica-Bold")
RIGHT = ParagraphStyle("right", parent=BODY, alignment=TA_RIGHT)
BOLD = ParagraphStyle("bold", parent=BODY, fontName="Helvetica-Bold")


def _p(text: str | None, style=BODY) -> Paragraph:
    return Paragraph(escape(text or "").replace("\n", "<br/>"), style)


@dataclass
class Party:
    name: str
    lines: list[str] = field(default_factory=list)


@dataclass
class InvoiceDoc:
    title: str  # "Tax invoice" / "Invoice"
    number: str
    issue_date: date | None
    due_date: date | None
    currency: str
    seller: Party
    buyer: Party
    lines: list[dict]  # description, quantity, unit, discount, tax_name, total
    subtotal: int
    breakdown: list[dict]  # name, rate_bp, amount
    total: int
    paid: int
    installments: list[dict]  # due_date, amount, paid
    bank_details: str | None = None
    upi: tuple[str, str, int] | None = None  # (upi id, payee name, amount to scan)
    links: list[tuple[str, int]] = field(default_factory=list)  # (url, amount)
    notes: str | None = None
    terms: str | None = None
    void_reason: str | None = None


def _fmt(d: date | None) -> str:
    return d.strftime("%d %b %Y") if d else "—"


def _upi_uri(upi_id: str, name: str, amount: int, note: str) -> str:
    return (
        f"upi://pay?pa={quote(upi_id)}&pn={quote(name[:50])}&am={plain(amount, 'INR')}"
        f"&cu=INR&tn={quote(note[:50])}"
    )


def _qr(data: str, size_mm: float = 34) -> Drawing:
    widget = QrCodeWidget(data)
    x0, y0, x1, y1 = widget.getBounds()
    size = size_mm * mm
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    return drawing


def _table(rows, widths, header=True, align_right_from=1) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style += [
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
            ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
        ]
    t.setStyle(TableStyle(style))
    return t


def _party(label: str, party: Party) -> list:
    return [_p(label, SMALL), _p(party.name, BOLD), *[_p(x) for x in party.lines if x]]


def invoice(doc: InvoiceDoc) -> bytes:
    buf = BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{doc.title} {doc.number}",
        author=doc.seller.name,
    )
    width = A4[0] - 36 * mm
    cur = doc.currency
    story: list = []
    head = Table(
        [
            [
                [_p(doc.seller.name, TITLE), *[_p(x, SMALL) for x in doc.seller.lines if x]],
                [
                    _p(
                        doc.title.upper(),
                        ParagraphStyle("t", parent=RIGHT, fontSize=14, fontName="Helvetica-Bold"),
                    ),
                    _p(doc.number, RIGHT),
                    _p(f"Date: {_fmt(doc.issue_date)}", RIGHT),
                    _p(f"Due: {_fmt(doc.due_date)}", RIGHT),
                ],
            ]
        ],
        colWidths=[width * 0.6, width * 0.4],
    )
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [head, Spacer(1, 8 * mm)]
    if doc.void_reason:
        story += [
            _p(
                f"VOID — {doc.void_reason}",
                ParagraphStyle("v", parent=BOLD, fontSize=12, textColor=colors.HexColor("#c0392b")),
            ),
            Spacer(1, 4 * mm),
        ]
    story += [Table([[_party("Bill to", doc.buyer)]], colWidths=[width]), Spacer(1, 6 * mm)]

    rows = [["Description", "Qty", "Unit price", "Discount", "Tax", "Amount"]]
    for ln in doc.lines:
        rows.append(
            [
                _p(ln["description"]),
                str(ln["quantity"]),
                display(ln["unit"], cur),
                display(ln["discount"], cur) if ln["discount"] else "—",
                ln["tax_name"] or "—",
                display(ln["total"], cur),
            ]
        )
    story.append(_table(rows, [width * w for w in (0.34, 0.07, 0.16, 0.13, 0.12, 0.18)]))
    story.append(Spacer(1, 4 * mm))

    sums = [["Subtotal", display(doc.subtotal, cur)]]
    for b in doc.breakdown:
        rate = b["rate_bp"] / 100
        sums.append([f"{b['name']} {rate:g}%", display(b["amount"], cur)])
    sums.append(["Total", display(doc.total, cur)])
    if doc.paid:
        sums += [
            ["Paid", display(doc.paid, cur)],
            ["Balance due", display(doc.total - doc.paid, cur)],
        ]
    t = Table(sums, colWidths=[width * 0.25, width * 0.2], hAlign="RIGHT")
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                (
                    "FONT",
                    (0, len(sums) - (3 if doc.paid else 1)),
                    (-1, len(sums) - (3 if doc.paid else 1)),
                    "Helvetica-Bold",
                    10,
                ),
                (
                    "LINEABOVE",
                    (0, len(sums) - (3 if doc.paid else 1)),
                    (-1, len(sums) - (3 if doc.paid else 1)),
                    0.6,
                    LINE,
                ),
            ]
        )
    )
    story += [t, Spacer(1, 6 * mm)]

    if len(doc.installments) > 1:
        rows = [["#", "Due date", "Amount", "Paid", "Left"]]
        for i, inst in enumerate(doc.installments, 1):
            rows.append(
                [
                    str(i),
                    _fmt(inst["due_date"]),
                    display(inst["amount"], cur),
                    display(inst["paid"], cur),
                    display(inst["amount"] - inst["paid"], cur),
                ]
            )
        story += [
            _p("Installments", BOLD),
            Spacer(1, 2 * mm),
            _table(rows, [width * w for w in (0.06, 0.24, 0.24, 0.23, 0.23)], align_right_from=2),
            Spacer(1, 6 * mm),
        ]

    if not doc.void_reason and doc.total > doc.paid and (doc.links or doc.bank_details or doc.upi):
        left: list = [_p("How to pay", BOLD)]
        for url, amount in doc.links:
            left.append(_p(f"Pay {display(amount, cur)} online: {url}"))
        if doc.bank_details:
            left += [Spacer(1, 2 * mm), _p("Bank transfer", SMALL), _p(doc.bank_details)]
        right: list = []
        if doc.upi:
            upi_id, name, amount = doc.upi
            right = [
                _qr(_upi_uri(upi_id, name, amount, doc.number)),
                _p(f"Scan with any UPI app: {display(amount, cur)}", SMALL),
                _p(upi_id, SMALL),
            ]
        pay = Table([[left, right]], colWidths=[width * 0.68, width * 0.32])
        pay.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [pay, Spacer(1, 6 * mm)]

    if doc.notes:
        story += [_p("Notes", SMALL), _p(doc.notes), Spacer(1, 3 * mm)]
    if doc.terms:
        story += [_p("Terms", SMALL), _p(doc.terms, SMALL)]
    pdf.build(story)
    return buf.getvalue()


@dataclass
class ReceiptDoc:
    number: str
    paid_on: date
    currency: str
    amount: int
    method: str
    reference: str | None
    invoice_number: str
    balance_after: int
    seller: Party
    buyer: Party
    reversed_reason: str | None = None


def receipt(doc: ReceiptDoc) -> bytes:
    buf = BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Receipt {doc.number}",
        author=doc.seller.name,
    )
    width = A4[0] - 36 * mm
    cur = doc.currency
    story: list = [
        _p(doc.seller.name, TITLE),
        *[_p(x, SMALL) for x in doc.seller.lines if x],
        Spacer(1, 8 * mm),
        _p(f"RECEIPT {doc.number}", ParagraphStyle("r", parent=BOLD, fontSize=14)),
        Spacer(1, 4 * mm),
    ]
    if doc.reversed_reason:
        story += [
            _p(
                f"REVERSED — {doc.reversed_reason}",
                ParagraphStyle("v", parent=BOLD, textColor=colors.HexColor("#c0392b")),
            ),
            Spacer(1, 3 * mm),
        ]
    rows = [
        ["Received from", doc.buyer.name],
        ["Amount", display(doc.amount, cur)],
        ["Date", _fmt(doc.paid_on)],
        ["Method", doc.method],
        ["Reference", doc.reference or "—"],
        ["For invoice", doc.invoice_number],
        ["Balance after this payment", display(doc.balance_after, cur)],
    ]
    t = Table(rows, colWidths=[width * 0.35, width * 0.65])
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
                ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("FONT", (1, 1), (1, 1), "Helvetica-Bold", 12),
            ]
        )
    )
    story += [t, Spacer(1, 8 * mm), _p("Thank you for your payment.", BODY)]
    pdf.build(story)
    return buf.getvalue()
