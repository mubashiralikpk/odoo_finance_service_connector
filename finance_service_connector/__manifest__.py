# -*- coding: utf-8 -*-
{
    'name': 'Finance Service Connector',
    'version': '17.0.1.1.0',
    'summary': 'Sync Odoo invoices to an external Finance-as-a-Service API',
    'author': 'Pitstop CRM',
    'website': 'https://github.com/mubashiralikpk/odoo_finance_service_connector',
    'category': 'Accounting/Finance',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'views/account_move_finance_form.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'finance_service_connector/static/src/scss/finance_form.scss',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
