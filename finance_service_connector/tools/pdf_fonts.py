# -*- coding: utf-8 -*-
"""PDF/A rule 6.2.11.5 (ISO 19005-2/-3): the glyph widths in the PDF font dictionary must match
the widths in the embedded font program.

wkhtmltopdf writes widths that are ~1 % off. Odoo corrects them only when the optional
``fonttools`` package is installed (it is not in the official Odoo Docker image), and even then
skips glyph 0. This module reads the embedded TrueType tables directly, so it needs no extra
package, and rewrites /W for every embedded CID TrueType font (CIDFontType2)."""
import logging
import struct

from odoo.tools.pdf import ArrayObject, NameObject, NumberObject

_logger = logging.getLogger(__name__)


def _stream_data(obj):
    obj = obj.getObject()
    return obj.get_data() if hasattr(obj, 'get_data') else obj.getData()


def _tables(data):
    num = struct.unpack('>H', data[4:6])[0]
    tables = {}
    for i in range(num):
        tag, _checksum, offset, length = struct.unpack('>4sIII', data[12 + 16 * i: 28 + 16 * i])
        tables[tag.decode('latin-1')] = (offset, length)
    return tables


def truetype_advance_widths(data):
    """Advance width of every glyph, in PDF glyph space (1/1000 em), from a TrueType font file."""
    t = _tables(data)
    head, hhea, hmtx, maxp = (t[k][0] for k in ('head', 'hhea', 'hmtx', 'maxp'))
    units_per_em = struct.unpack('>H', data[head + 18: head + 20])[0]
    num_hmetrics = struct.unpack('>H', data[hhea + 34: hhea + 36])[0]
    num_glyphs = struct.unpack('>H', data[maxp + 4: maxp + 6])[0]
    advances = [struct.unpack('>H', data[hmtx + 4 * i: hmtx + 4 * i + 2])[0] for i in range(num_hmetrics)]
    advances += [advances[-1]] * max(0, num_glyphs - num_hmetrics)  # monospaced tail repeats the last width
    return [round(1000.0 * a / units_per_em) for a in advances[:num_glyphs]]


def fix_glyph_widths(writer):
    """Rewrite /W of each CIDFontType2 font so it matches the embedded font program. Returns fonts fixed."""
    fixed, seen = 0, set()
    pages = writer._root_object['/Pages'].getObject()
    stack = list(pages['/Kids'])
    while stack:
        node = stack.pop().getObject()
        if node.get('/Type') == '/Pages':
            stack.extend(node['/Kids'])
            continue
        resources = node.get('/Resources')
        fonts = resources.getObject().get('/Font') if resources else None
        for font_ref in (fonts.getObject().values() if fonts else []):
            font = font_ref.getObject()
            if font.get('/Subtype') != '/Type0':
                continue
            for desc_ref in font['/DescendantFonts']:
                key = getattr(desc_ref, 'idnum', id(desc_ref))
                if key in seen:
                    continue
                seen.add(key)
                cid_font = desc_ref.getObject()
                descriptor = cid_font.get('/FontDescriptor')
                file2 = descriptor.getObject().get('/FontFile2') if descriptor else None
                if cid_font.get('/Subtype') != '/CIDFontType2' or file2 is None:
                    continue
                try:
                    widths = truetype_advance_widths(_stream_data(file2))
                    cid_to_gid = cid_font.get('/CIDToGIDMap')
                    if cid_to_gid is not None and not isinstance(cid_to_gid, str) and cid_to_gid != '/Identity':
                        raw = _stream_data(cid_to_gid)
                        gids = [struct.unpack('>H', raw[i:i + 2])[0] for i in range(0, len(raw) - 1, 2)]
                        widths = [widths[g] if g < len(widths) else 0 for g in gids]
                    cid_font[NameObject('/W')] = ArrayObject([
                        NumberObject(0), ArrayObject([NumberObject(w) for w in widths])])
                    fixed += 1
                except Exception:  # noqa: BLE001  a font we cannot parse keeps its widths
                    _logger.warning('PDF/A: could not read glyph widths of %s', font.get('/BaseFont'), exc_info=True)
    return fixed
