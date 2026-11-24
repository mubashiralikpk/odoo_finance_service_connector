# -*- coding: utf-8 -*-
from odoo import api, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    @api.model_create_multi
    def create(self, vals_list):
        # GoBD: customer invoice journals are hash-locked from the start
        for vals in vals_list:
            if vals.get('type') == 'sale':
                vals.setdefault('restrict_mode_hash_table', True)
        return super().create(vals_list)
