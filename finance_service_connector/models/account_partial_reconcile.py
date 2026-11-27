# -*- coding: utf-8 -*-
from odoo import api, models


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    def _fsc_invoices(self):
        return (self.debit_move_id.move_id | self.credit_move_id.move_id).filtered(
            lambda m: m.move_type in ('out_invoice', 'out_refund'))

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        partials._fsc_invoices()._fsc_sync_view_pdf()   # paid / cancelled -> stamped copy
        return partials

    def unlink(self):
        invoices = self._fsc_invoices()
        res = super().unlink()
        invoices.exists()._fsc_sync_view_pdf()           # payment removed -> back to the original
        return res
