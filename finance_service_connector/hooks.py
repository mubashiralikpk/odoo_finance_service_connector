# -*- coding: utf-8 -*-


def post_init_hook(env):
    """Switch on Odoo's own GoBD helpers, map the German 0 % taxes and put
    invoices that were already posted under the GoBD rules."""
    env['res.company'].search([])._fsc_apply_gobd_defaults()
    env['account.move']._fsc_adopt_existing_invoices()
