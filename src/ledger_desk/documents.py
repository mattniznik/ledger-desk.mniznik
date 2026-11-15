"""Render each sample invoice from its YAML ground truth: a PDF, or a phone photo.

PDFs are drawn with reportlab, which is pure Python, rather than an HTML template printed by a
browser (Playwright or WeasyPrint; WeasyPrint needs system libraries on Windows). They have a real
text layer, which the reading check needs: code checks that every field Claude reads is really in the PDF's text. `invariant=1`
makes the bytes identical on every render.

Each vendor gets one of three layouts, so the reader cannot rely on fields always sitting in the
same place. The photo variant is drawn with Pillow: paper on a darker table, rotated 1-3 degrees,
with noise and a little blur. It has no text layer at all. Its noise comes from a seeded random
generator, because Pillow's own noise function cannot be seeded.
"""

from __future__ import annotations

import io
import os
import random
import time
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

from .company import COMPANY_NAME
from .invoices import Case

LAYOUTS = ("classic", "banded", "minimal")

LAYOUT_BY_VENDOR = {
    "Green Coffee Importer": "classic",
    "Dairy Supplier": "banded",
    "Packaging Supplier": "minimal",
    "Roasting Equipment Supplier": "classic",
    "Espresso Repair Service": "banded",
    "Electric Utility": "minimal",
    "Freight Carrier": "classic",
    "POS Software Vendor": "banded",
}


def layout_for(vendor_name: str) -> str:
    return LAYOUT_BY_VENDOR.get(vendor_name, "classic")


def _usd(value) -> str:
    return f"${value:,.2f}" if value >= 0 else f"-${-value:,.2f}"


def _lines_of(case: Case) -> list[str]:
    """The invoice as plain text lines, shared by the photo renderer."""
    inv = case.invoice
    title = "CREDIT MEMO" if inv.kind == "credit_memo" else "INVOICE"
    out = [inv.vendor_name, f"Tax id {inv.vendor_tax_id}", "", f"{title} {inv.number}", f"Date {inv.date.isoformat()}"]
    if inv.po:
        out.append(f"Purchase order {inv.po}")
    if inv.refers_to:
        out.append(f"Credits invoice {inv.refers_to}")
    out += [f"Bill to: {COMPANY_NAME}", ""]
    for l in inv.lines:
        out.append(f"{l.description}  {l.quantity} x {_usd(l.unit_price)} = {_usd(l.amount)}")
    out += ["", f"Subtotal {_usd(inv.subtotal)}", f"Tax {_usd(inv.tax)}", f"TOTAL {_usd(inv.total)}", ""]
    out.append(f"Remit to {inv.remit_to.bank}, account ending {inv.remit_to.account_last4}")
    out += inv.notes
    return out


def render_pdf(case: Case, path: Path) -> Path:
    inv = case.invoice
    layout = case.layout or layout_for(inv.vendor_name)
    width, height = LETTER
    c = Canvas(str(path) if isinstance(path, Path) else path, pagesize=LETTER, invariant=1)  # a path or a buffer
    c.setTitle(f"{inv.vendor_name} {inv.number}")
    title = "CREDIT MEMO" if inv.kind == "credit_memo" else "INVOICE"

    # Header: where the vendor and the document title sit depends on the layout.
    if layout == "banded":
        c.setFillColor(HexColor("#1f3a5f"))
        c.rect(0, height - 90, width, 90, stroke=0, fill=1)
        c.setFillColor(HexColor("#ffffff"))
        c.setFont("Helvetica-Bold", 18)
        c.drawString(40, height - 50, inv.vendor_name)
        c.setFont("Helvetica", 11)
        c.drawString(40, height - 70, f"Tax id {inv.vendor_tax_id}")
        c.drawRightString(width - 40, height - 50, f"{title} {inv.number}")
        c.setFillColor(HexColor("#000000"))
        y = height - 120
    elif layout == "minimal":
        c.setFont("Helvetica-Bold", 14)
        c.drawRightString(width - 40, height - 50, inv.vendor_name)
        c.setFont("Helvetica", 9)
        c.drawRightString(width - 40, height - 64, f"Tax id {inv.vendor_tax_id}")
        c.setFont("Helvetica-Bold", 22)
        c.drawString(40, height - 60, title)
        c.setFont("Helvetica", 11)
        c.drawString(40, height - 80, f"No. {inv.number}")
        y = height - 115
    else:
        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, height - 50, inv.vendor_name)
        c.setFont("Helvetica", 10)
        c.drawString(40, height - 66, f"Tax id {inv.vendor_tax_id}")
        c.setFont("Helvetica-Bold", 13)
        c.drawRightString(width - 40, height - 50, title)
        c.setFont("Helvetica", 11)
        c.drawRightString(width - 40, height - 66, inv.number)
        y = height - 110

    c.setFont("Helvetica", 10)
    meta = [f"Date: {inv.date.isoformat()}", f"Bill to: {COMPANY_NAME}"]
    if inv.po:
        meta.append(f"Purchase order: {inv.po}")
    if inv.refers_to:
        meta.append(f"Credits invoice: {inv.refers_to}")
    for text in meta:
        c.drawString(40, y, text)
        y -= 15

    # Line table.
    y -= 15
    c.setFont("Helvetica-Bold", 10)
    for x, label, right in [(40, "Description", False), (360, "Qty", True), (450, "Unit price", True), (width - 40, "Amount", True)]:
        (c.drawRightString if right else c.drawString)(x, y, label)
    c.line(40, y - 4, width - 40, y - 4)
    c.setFont("Helvetica", 10)
    for line in inv.lines:
        if y < 150:  # a long statement continues on the next page, with the table header again
            c.showPage()
            c.setFont("Helvetica", 9)
            c.drawString(40, height - 40, f"{inv.vendor_name}, {title.lower()} {inv.number}, continued")
            y = height - 70
            c.setFont("Helvetica-Bold", 10)
            for x, label, right in [(40, "Description", False), (360, "Qty", True), (450, "Unit price", True), (width - 40, "Amount", True)]:
                (c.drawRightString if right else c.drawString)(x, y, label)
            c.line(40, y - 4, width - 40, y - 4)
            c.setFont("Helvetica", 10)
        y -= 18
        c.drawString(40, y, line.description[:58])
        c.drawRightString(360, y, f"{line.quantity:,}")
        c.drawRightString(450, y, _usd(line.unit_price))
        c.drawRightString(width - 40, y, _usd(line.amount))

    y -= 30
    for label, value, bold in [("Subtotal", inv.subtotal, False), ("Tax", inv.tax, False), ("Total due", inv.total, True)]:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11 if bold else 10)
        if bold:
            c.setFillGray(ink_for(case, "total") / 255)
        c.drawRightString(450, y, label)
        c.drawRightString(width - 40, y, _usd(inv.total if bold else value))
        c.setFillGray(0)
        y -= 16

    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Remit to: {inv.remit_to.bank}, account ending {inv.remit_to.account_last4}")

    # Notes in small print at the foot of the page: where a hidden instruction would sit.
    c.setFont("Helvetica", 8)
    fy = 60
    for note in inv.notes:
        c.drawString(40, fy, note)
        fy -= 11
    c.showPage()
    c.save()
    return path


def ink_for(case: Case, part: str) -> int:
    """Grey level a part of the document is printed in (0 black, 255 white). The hard tier can
    wash out the total, the field a misread would cost most."""
    if part == "total" and (case.render or {}).get("faint_total"):
        return 175
    return 30


def render_photo(case: Case, path: Path) -> Path:
    """A phone photo of the invoice. With no render options it is the same image as always (same
    seed, same order of random draws); the hard tier's options make it skewed, blurred, noisy,
    shadowed, creased, written on, small or heavily compressed."""
    opts = case.render or {}
    rng = random.Random(f"photo-{case.id}")
    paper = Image.new("L", (1240, 1600), 248)
    draw = ImageDraw.Draw(paper)
    font = ImageFont.load_default(size=30)
    y = 80
    for text in _lines_of(case):
        draw.text((80, y), text, fill=ink_for(case, "total") if text.startswith("TOTAL") else 30, font=font)
        y += 44
    if opts.get("crease"):
        draw.line([(0, 520), (1240, 760)], fill=236, width=6)
        draw.line([(0, 526), (1240, 766)], fill=200, width=2)
    if opts.get("handwritten"):
        note = Image.new("L", (900, 90), 0)
        ImageDraw.Draw(note).text((10, 10), opts["handwritten"], fill=255, font=ImageFont.load_default(size=46))
        note = note.rotate(-8, expand=True, resample=Image.Resampling.BICUBIC)
        paper.paste(Image.new("L", note.size, 70), (300, 1080), note)
    if opts.get("shadow"):
        shade = Image.linear_gradient("L").rotate(90).resize(paper.size)  # dark on the left, fading out
        paper = Image.composite(Image.new("L", paper.size, 90), paper, shade.point(lambda v: int(v * 0.55)))

    angle = opts["angle"] if "angle" in opts else 1 + rng.random() * 2
    rotated = paper.rotate(angle, expand=True, fillcolor=110, resample=Image.Resampling.BICUBIC)
    table = Image.new("L", (rotated.width + 120, rotated.height + 120), 110)
    table.paste(rotated, (60, 60))

    noise = Image.frombytes("L", table.size, rng.randbytes(table.width * table.height))
    photo = Image.blend(table, noise, opts.get("noise", 0.06)).filter(ImageFilter.GaussianBlur(opts.get("blur", 0.9)))
    if "scale" in opts:
        photo = photo.resize((int(photo.width * opts["scale"]), int(photo.height * opts["scale"])), Image.Resampling.LANCZOS)
    photo.save(path, "JPEG", quality=opts.get("quality", 82))
    return path


def render_case(case: Case, out_dir: Path) -> Path:
    """Render a sample's document into out_dir and return its path.

    Two visitors opening the same sample would otherwise write the same file while the other reads it
    (measured in the browser tests: an empty file, and the bill fell out of the queue). The document is
    rendered in memory first; the render is byte for byte the same each time (invariant=1, a seeded photo),
    so when the file on disk already holds those bytes it is left alone, and a reader can never meet a
    write. A changed bill is written to a temporary file beside it and swapped in with one atomic replace,
    so a reader sees the whole old file or the whole new one."""
    out_dir.mkdir(parents=True, exist_ok=True)
    photo = case.document == "photo"
    final = out_dir / f"{case.slug}.{'jpg' if photo else 'pdf'}"
    buf = io.BytesIO()
    (render_photo if photo else render_pdf)(case, buf)
    data = buf.getvalue()
    try:
        if final.read_bytes() == data:
            return final
    except FileNotFoundError:
        pass
    tmp = final.with_name(f".{final.stem}.{uuid.uuid4().hex}{final.suffix}")
    try:
        tmp.write_bytes(data)
        _replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)
    return final


def _replace(tmp: Path, final: Path, tries: int = 100, wait: float = 0.01) -> None:
    # On Windows a file another request still has open cannot be replaced (PermissionError): keep trying for about
    # a second, long enough for a reader to finish with a bill this size. Linux replaces it at once.
    for _ in range(tries):
        try:
            os.replace(tmp, final)
            return
        except PermissionError:
            time.sleep(wait)
    raise PermissionError(f"could not replace {final}")
