# -*- coding: utf-8 -*-
"""German chart (SKR03: EUR, 19 % / 7 % / 0 %) for companies without any accounting entry yet."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env['res.company'].search([])
    companies._fsc_ensure_german_chart()
    companies._fsc_apply_gobd_defaults()
