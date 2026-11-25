# -*- coding: utf-8 -*-
"""PDF rule: every issued customer invoice is a PDF/A-3 hybrid document with
the EN 16931 Factur-X XML embedded, whatever the customer's e-invoice format."""
import io
import logging

from odoo import api, fields, models, tools

from ..tools.pdf_fonts import fix_glyph_widths
from odoo.tools.pdf import DictionaryObject, NameObject, NumberObject, OdooPdfFileReader, OdooPdfFileWriter, createStringObject

_logger = logging.getLogger(__name__)


class AccountMoveSend(models.TransientModel):
    _inherit = 'account.move.send'

    @api.model
    def _hook_invoice_document_after_pdf_report_render(self, invoice, invoice_data):
        super()._hook_invoice_document_after_pdf_report_render(invoice, invoice_data)
        if tools.config['test_enable'] or invoice.move_type not in ('out_invoice', 'out_refund'):
            return
        pdf_values = invoice_data.get('pdf_attachment_values')
        if not pdf_values or not pdf_values.get('raw'):
            return
        reader = OdooPdfFileReader(io.BytesIO(pdf_values['raw']), strict=False)
        writer = OdooPdfFileWriter()
        writer.cloneReaderDocumentRoot(reader)
        if not writer.is_pdfa:  # Odoo converts only for ZUGFeRD / Factur-X customers
            if '/Outlines' not in writer._root_object:
                # Odoo's converter expects an outline tree; some wkhtmltopdf builds do not write one.
                outlines = writer._addObject(DictionaryObject({
                    NameObject('/Type'): NameObject('/Outlines'),
                    NameObject('/Count'): NumberObject(0),
                }))
                writer._root_object[NameObject('/Outlines')] = outlines
            try:
                writer.convert_to_pdfa()
            except Exception as e:  # noqa: BLE001
                _logger.exception('GoBD: PDF/A conversion failed for %s: %s', invoice.name, e)
                return
            metadata = self.env['ir.qweb']._render(
                'account_edi_ubl_cii.account_invoice_pdfa_3_facturx_metadata',
                {'title': invoice.name, 'date': fields.Date.context_today(self)},
            )
            writer.add_file_metadata(metadata.encode())
        # PDF/A 6.2.11.5: glyph widths must match the embedded fonts (Odoo only fixes them with fonttools)
        fix_glyph_widths(writer)
        # document language (the PDF is printed in the customer's language)
        lang = invoice.partner_id.lang or invoice.company_id.partner_id.lang or self.env.lang or 'en_US'
        writer._root_object[NameObject('/Lang')] = createStringObject(lang.replace('_', '-'))
        buffer = io.BytesIO()
        writer.write(buffer)
        pdf_values['raw'] = buffer.getvalue()
