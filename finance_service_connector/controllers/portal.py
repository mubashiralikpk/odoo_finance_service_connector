# -*- coding: utf-8 -*-
from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.account.controllers.portal import PortalAccount


class FscPortalAccount(PortalAccount):

    @http.route()
    def portal_my_invoice_detail(self, invoice_id, access_token=None, report_type=None, download=False, **kw):
        """Customer portal download: the issued original with a PAID / CANCELLED stamp."""
        if report_type == 'pdf' and download:
            try:
                invoice = self._document_check_access('account.move', invoice_id, access_token)
            except (AccessError, MissingError):
                return request.redirect('/my')
            if (invoice.state == 'posted' and invoice.fsc_is_gobd_document
                    and invoice.move_type in ('out_invoice', 'out_refund') and invoice._fsc_stamp_kind()):
                original = invoice._fsc_original_pdf()
                if original:
                    content = invoice._fsc_stamped_pdf(original)
                    headers = self._get_http_headers(invoice, 'pdf', content, download)
                    return request.make_response(content, list(headers.items()))
        return super().portal_my_invoice_detail(invoice_id, access_token=access_token, report_type=report_type,
                                                download=download, **kw)
