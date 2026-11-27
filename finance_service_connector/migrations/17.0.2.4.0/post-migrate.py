# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Document versions: the archived originals become version 1 (issued, active - set by the
    column defaults). Paid / cancelled copies made by 17.0.2.3.0 are registered as version 2."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Archive = env['fsc.invoice.archive'].sudo()
    moves = env['account.move'].search([('fsc_view_pdf_id', '!=', False)])
    for move in moves:
        copy = move.fsc_view_pdf_id
        if Archive.search_count([('attachment_id', '=', copy.id)]):
            continue
        original = move.fsc_archive_ids.filtered(lambda a: a.kind == 'pdf' and a.stamp == 'issued')[:1]
        Archive.create({
            'move_id': move.id, 'kind': 'pdf', 'attachment_id': copy.id,
            'standard': original.standard or 'PDF/A-3 + Factur-X (copy with status stamp)',
            'version': 2, 'stamp': move.fsc_view_pdf_kind or 'paid', 'state': 'active',
            'trigger': 'Migration 17.0.2.4.0',
        })
    env['account.move'].search([
        ('move_type', 'in', ('out_invoice', 'out_refund')), ('state', '=', 'posted'),
        ('payment_state', 'in', ('paid', 'in_payment', 'reversed')),
    ])._fsc_sync_view_pdf(trigger='Migration 17.0.2.4.0')
