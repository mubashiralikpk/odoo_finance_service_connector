# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Create the stamped PDF copies (BEZAHLT / STORNIERT) for invoices that are already paid or cancelled."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    moves = env['account.move'].search([
        ('move_type', 'in', ('out_invoice', 'out_refund')), ('state', '=', 'posted'),
        ('payment_state', 'in', ('paid', 'in_payment', 'reversed')),
    ])
    moves._fsc_sync_view_pdf()
