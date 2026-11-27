# -*- coding: utf-8 -*-
from odoo import models



class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """Print / preview of one customer invoice: the issued original (with its embedded
        e-invoice XML) plus a status stamp - PAID, CANCELLED or DRAFT - like the Pitstop CRM.
        The archived original itself is never changed (GoBD)."""
        content, report_type = super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
        if (report_type != 'pdf' or not self._is_invoice_report(report_ref) or not res_ids
                or self.env.context.get('from_account_move_send') or self.env.context.get('fsc_no_stamp')):
            return content, report_type
        ids = [res_ids] if isinstance(res_ids, int) else list(res_ids)
        if len(ids) != 1:
            return content, report_type
        move = self.env['account.move'].browse(ids)
        if not move.fsc_is_gobd_document or move.move_type not in ('out_invoice', 'out_refund'):
            return content, report_type
        original = move._fsc_original_pdf()
        if original:
            content = original
        return move._fsc_stamped_pdf(content), report_type
