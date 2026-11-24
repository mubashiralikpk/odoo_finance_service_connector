# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountTax(models.Model):
    _inherit = 'account.tax'

    fsc_legal_note = fields.Char(
        string='Legal note on invoice', translate=True,
        help='Statement printed on the invoice for this VAT treatment, e.g. the exemption '
             'paragraph (§14 Abs. 4 Nr. 8 UStG) or "Steuerfreie innergemeinschaftliche '
             'Lieferung". For reverse charge (AE) the statutory phrase '
             '"Steuerschuldnerschaft des Leistungsempfängers" is printed when empty.')
