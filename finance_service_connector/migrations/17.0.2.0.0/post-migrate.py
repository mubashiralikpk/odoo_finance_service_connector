# -*- coding: utf-8 -*-
"""1.x (Finance Service sync) → 2.0 (standalone GoBD invoicing)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.company'].search([])._fsc_apply_gobd_defaults()
    env['account.move']._fsc_adopt_existing_invoices()
    # Columns of the removed Finance Service sync (kept by Odoo after field removal)
    for table, column in (
        ('res_company', 'fs_api_url'), ('res_company', 'fs_api_key'),
        ('res_company', 'fs_tenant_id'), ('res_company', 'fs_auto_sync'),
        ('account_move', 'fs_invoice_id'), ('account_move', 'fs_invoice_number'),
        ('account_move', 'fs_sync_state'), ('account_move', 'fs_sync_error'),
        ('account_move', 'fs_synced_at'),
    ):
        cr.execute(f'ALTER TABLE {table} DROP COLUMN IF EXISTS {column}')
