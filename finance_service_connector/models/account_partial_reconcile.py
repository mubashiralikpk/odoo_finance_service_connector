# -*- coding: utf-8 -*-
from odoo import _, api, models


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    def _fsc_by_invoice(self):
        """{invoice: names of the counterpart documents (payment, credit note, Storno)}"""
        result = {}
        for partial in self:
            moves = partial.debit_move_id.move_id | partial.credit_move_id.move_id
            for move in moves.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund')):
                result.setdefault(move, set()).update((moves - move).mapped('name'))
        return result

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        for move, names in partials._fsc_by_invoice().items():
            move._fsc_sync_view_pdf(trigger=_('Reconciled with %s', ', '.join(sorted(n for n in names if n))))
        return partials

    def unlink(self):
        by_invoice = self._fsc_by_invoice()
        res = super().unlink()
        for move, names in by_invoice.items():
            if move.exists():
                move._fsc_sync_view_pdf(trigger=_('Reconciliation removed: %s', ', '.join(sorted(n for n in names if n))))
        return res
