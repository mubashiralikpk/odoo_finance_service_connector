# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class FscCancelWizard(models.TransientModel):
    """Cancel an issued invoice with a cancellation invoice (Stornorechnung).

    GoBD: an issued invoice is never deleted or changed. It is cancelled by a second
    document for the full amount, which is issued, archived and linked to it."""
    _name = 'fsc.cancel.wizard'
    _description = 'Cancel invoice (Storno)'

    move_id = fields.Many2one('account.move', required=True, readonly=True)
    move_name = fields.Char(related='move_id.name')
    amount_total = fields.Monetary(related='move_id.amount_total')
    currency_id = fields.Many2one(related='move_id.currency_id')
    reason = fields.Text(required=True)
    date = fields.Date(string='Cancellation date', required=True, default=fields.Date.context_today)
    create_replacement = fields.Boolean(
        string='Create a new invoice to correct and send again', default=True,
        help='After the cancellation, a new draft invoice with the same member, address and articles '
             'is created. Change what is wrong, then issue and send it.')

    def action_cancel(self):
        self.ensure_one()
        move = self.move_id
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_('A reason is required.'))
        if move.move_type != 'out_invoice' or move.state != 'posted':
            raise UserError(_('Only issued customer invoices can be cancelled.'))
        if move.fsc_status == 'cancelled':
            raise UserError(_('%s is already cancelled.', move.name))
        if move.payment_state != 'not_paid':
            raise UserError(_('%s already has payments. Refund the payment first, or issue a credit note '
                              'for the amount to correct.', move.name))
        cancellation = move._reverse_moves([{
            'ref': _('Cancellation of %(name)s: %(reason)s', name=move.name, reason=reason),
            'invoice_date': self.date,
            'date': self.date,
            'fs_document_title': 'Cancellation invoice',
            'partner_bank_id': move.partner_bank_id.id,
        }], cancel=True)
        move._fsc_log('cancelled', reason=reason, new={'cancellation': cancellation.name})
        if self.create_replacement:
            replacement = move.copy({
                'fsc_replaces_id': move.id,
                'invoice_date': False,
                'invoice_date_due': False,
                'fs_document_title': False,
            })
            replacement.message_post(body=_('Replacement for %(name)s (cancelled by %(storno)s).',
                                            name=move.name, storno=cancellation.name))
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': replacement.id,
                'view_mode': 'form',
            }
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': cancellation.id,
            'view_mode': 'form',
        }
