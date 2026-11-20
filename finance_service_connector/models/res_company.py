# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    fs_api_url = fields.Char(
        string='Finance Service URL',
        help='Base URL of the Finance Service API, e.g. http://host.docker.internal:3000',
    )
    fs_api_key = fields.Char(
        string='Finance Service API Key',
        help="API key for this company's Finance Service tenant",
    )
    fs_tenant_id = fields.Char(
        string='Finance Service Tenant ID',
        help="UUID of this company's tenant in the Finance Service",
    )
    fs_auto_sync = fields.Boolean(
        string='Auto-sync on Invoice Confirmation',
        help='Automatically push invoices to Finance Service when confirmed',
        default=True,
    )
