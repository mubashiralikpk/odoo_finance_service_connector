# -*- coding: utf-8 -*-
"""Status stamps (PAID / CANCELLED / DRAFT) on invoice PDFs for preview and download,
the same way the Pitstop CRM marks its invoices.

GoBD: the stamp is only put on a *copy*. The issued original in the GoBD archive is
never changed (its SHA-256 stays valid); the copy keeps the embedded e-invoice XML."""
import io
import logging
import os

from odoo.tools.pdf import NameObject, OdooPdfFileReader, OdooPdfFileWriter

_logger = logging.getLogger(__name__)

STAMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'stamps')
STAMP_FILES = {
    ('paid', 'de'): 'paid_stamp_de.png',
    ('paid', 'en'): 'paid_stamp_en.png',
    ('cancelled', 'de'): 'cancelled_stamp_de.png',
    ('cancelled', 'en'): 'cancelled_stamp_en.png',
}
DRAFT_LABEL = {'de': 'Entwurf', 'en': 'Draft'}
MM = 72.0 / 25.4


def _stamp_image(kind, lang):
    from PIL import Image
    img = Image.open(os.path.join(STAMP_DIR, STAMP_FILES[(kind, lang)])).convert('RGBA')
    if kind == 'paid':
        img = img.rotate(22, expand=True, resample=Image.BICUBIC)   # tilted like the CRM's PAID stamp
    # soft rubber-stamp look (CRM: opacity 0.52)
    alpha = img.getchannel('A').point(lambda a: int(a * 0.55))
    img.putalpha(alpha)
    return img


def _overlay(kind, lang, width, height):
    """One transparent PDF page with the stamp, same size as the invoice page."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    if kind == 'draft':
        # grey corner ribbon, top left (CRM: "Entwurf")
        c.setFillColorRGB(0.37, 0.37, 0.37)
        p = c.beginPath()
        p.moveTo(0, height - 24 * MM)
        p.lineTo(24 * MM, height)
        p.lineTo(52 * MM, height)
        p.lineTo(0, height - 52 * MM)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        c.saveState()
        c.translate(15 * MM, height - 30 * MM)
        c.rotate(45)
        c.setFillColorRGB(1, 1, 1)
        c.setFont('Helvetica-Bold', 11)
        c.drawCentredString(0, 0, DRAFT_LABEL[lang])
        c.restoreState()
    else:
        img = _stamp_image(kind, lang)
        max_w, max_h = 58 * MM, 40 * MM
        w = max_w
        h = w * img.height / img.width
        if h > max_h:
            h = max_h
            w = h * img.width / img.height
        # centre of the article table area on page 1
        cx, cy = width / 2, height * 0.52
        # white scrub under the ink so the digits do not read through
        c.saveState()
        c.setFillColorRGB(1, 1, 1)
        c.setFillAlpha(0.45)
        sw, sh = max(w, h) * 0.92, min(w, h) * 0.55
        c.roundRect(cx - sw / 2, cy - sh / 2, sw, sh, 2.5 * MM, fill=1, stroke=0)
        c.restoreState()
        png = io.BytesIO()
        img.save(png, format='PNG')
        png.seek(0)
        c.drawImage(ImageReader(png), cx - w / 2, cy - h / 2, width=w, height=h, mask='auto')
    c.showPage()
    c.save()
    return buf.getvalue()


def stamp_pdf(pdf_bytes, kind, lang='en'):
    """Return a copy of pdf_bytes with the status stamp on page 1 (kind: paid, cancelled, draft)."""
    lang = 'de' if (lang or '').startswith('de') else 'en'
    try:
        reader = OdooPdfFileReader(io.BytesIO(pdf_bytes), strict=False)
        writer = OdooPdfFileWriter()
        writer.cloneReaderDocumentRoot(reader)   # keeps the embedded factur-x.xml and the metadata
        node = writer._root_object['/Pages'].getObject()
        while '/Kids' in node:                   # first page of the page tree
            node = node['/Kids'][0].getObject()
        first = reader.getPage(0)                # PageObject view of the same page
        box = first.mediaBox
        width, height = float(box.getWidth()), float(box.getHeight())
        overlay = OdooPdfFileReader(io.BytesIO(_overlay(kind, lang, width, height)), strict=False).getPage(0)
        getattr(first, 'merge_page', None) and first.merge_page(overlay) or first.mergePage(overlay)
        for key in ('/Contents', '/Resources'):
            node[NameObject(key)] = first[key]   # write the merged page back into the cloned document
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:  # noqa: BLE001  never block a download because of the stamp
        _logger.warning('Could not stamp the invoice PDF (%s)', kind, exc_info=True)
        return pdf_bytes
