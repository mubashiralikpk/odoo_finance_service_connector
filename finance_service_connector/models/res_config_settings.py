# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fsc_tax_number = fields.Char(related='company_id.fsc_tax_number', readonly=False)
    fsc_retention_years = fields.Integer(related='company_id.fsc_retention_years', readonly=False)
    fsc_b2b_require_vat = fields.Boolean(related='company_id.fsc_b2b_require_vat', readonly=False)
    fsc_hash_lock_active = fields.Boolean(
        string='Customer invoices locked with hash', compute='_compute_fsc_hash_lock_active')

    @api.depends('company_id')
    def _compute_fsc_hash_lock_active(self):
        for settings in self:
            journals = self.env['account.journal'].search([
                ('type', '=', 'sale'), ('company_id', '=', settings.company_id.id)])
            settings.fsc_hash_lock_active = bool(journals) and all(journals.mapped('restrict_mode_hash_table'))

    def action_fsc_enable_hash_lock(self):
        self.ensure_one()
        self.company_id._fsc_apply_gobd_defaults()

    def action_fsc_open_gobd_export(self):
        return self.env['ir.actions.actions']._for_xml_id('finance_service_connector.action_fsc_gobd_export')
