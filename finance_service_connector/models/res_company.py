# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

import logging

_logger = logging.getLogger(__name__)

# Odoo l10n_de (SKR03 / SKR04) sales taxes whose meaning is unambiguous.
# Everything else (exempt §4 Nr. 8-28, §19 small business, not taxable, ...)
# needs the company's own decision and stays blocked until it is set.
L10N_DE_VAT_CATEGORIES = {
    'tax_eu_sale': ('K', 'VATEX_EU_IC'),        # Steuerfreie innergem. Lieferung (§4 Nr. 1b UStG)
    'tax_free_newcar': ('K', 'VATEX_EU_IC'),    # Steuerfreie Neufahrzeuglieferung EU
    'tax_export': ('G', 'VATEX_EU_G'),          # Steuerfreie Ausfuhr (§4 Nr. 1a UStG)
    'tax_free_eu': ('AE', 'VATEX_EU_AE'),       # sonstige Leistung EU, Steuerschuldnerschaft des Empfängers
    'tax_ust_free_bau': ('AE', 'VATEX_EU_AE'),  # §13b Bauleistung
    'tax_ust_free_mobil': ('AE', 'VATEX_EU_AE'),  # §13b Mobilfunkgeräte
}


class ResCompany(models.Model):
    _inherit = 'res.company'

    fsc_tax_number = fields.Char(
        string='Tax number (Steuernummer)',
        help='Printed on invoices and written to the e-invoice (BT-32) when set. '
             '§14 Abs. 4 Nr. 2 UStG requires the VAT ID or the tax number.')
    fsc_retention_years = fields.Integer(
        string='Invoice retention (years)', default=8,
        help='Counted from the end of the issue year. The legal minimum is 8 years '
             '(§14b UStG, §147 AO).')
    check_account_audit_trail = fields.Boolean(default=True)

    @api.constrains('fsc_retention_years')
    def _check_fsc_retention_years(self):
        for company in self:
            if company.fsc_retention_years < 8:
                raise ValidationError(_('The legal minimum invoice retention is 8 years.'))

    def _fsc_ensure_german_chart(self):
        """German E-Invoice works with the German chart: SKR03 brings EUR and the
        19 %, 7 % and 0 % sales taxes. Only for companies without any accounting
        entry yet (Odoo cannot switch the chart afterwards)."""
        for company in self:
            if company.chart_template in ('de_skr03', 'de_skr04'):
                continue
            if company.country_id and company.country_id.code != 'DE':
                continue  # a non-German company keeps its own localisation
            if company._existing_accounting():
                _logger.info('GoBD: %s already has accounting entries; chart not changed.', company.name)
                continue
            self.env['account.chart.template'].try_loading('de_skr03', company, install_demo=True)  # demo only if the database has demo data

    def _fsc_apply_gobd_defaults(self):
        """Audit trail on, sales journals hash-locked, unambiguous German 0 % taxes
        mapped to their EN 16931 VAT category. Never overwrites a set category."""
        for company in self:
            company.check_account_audit_trail = True
            self.env['account.journal'].search([
                ('type', '=', 'sale'), ('company_id', '=', company.id),
                ('restrict_mode_hash_table', '=', False),
            ]).write({'restrict_mode_hash_table': True})
            data = self.env['ir.model.data'].sudo().search([
                ('model', '=', 'account.tax'), ('module', '=', 'account'),
                ('name', '=like', f'{company.id}\\_%'),
            ])
            for record in data:
                key = record.name[len(f'{company.id}_'):].rsplit('_skr', 1)[0]
                if key not in L10N_DE_VAT_CATEGORIES:
                    continue
                tax = self.env['account.tax'].browse(record.res_id).exists()
                if tax and not tax.ubl_cii_tax_category_code and not tax.amount:
                    category, reason = L10N_DE_VAT_CATEGORIES[key]
                    tax.write({'ubl_cii_tax_category_code': category,
                               'ubl_cii_tax_exemption_reason_code': reason})
