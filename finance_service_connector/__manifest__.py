# -*- coding: utf-8 -*-
{
    'name': 'German E-Invoice (GoBD, ZUGFeRD, XRechnung)',
    'version': '17.0.2.2.0',
    'summary': 'GoBD-compliant German invoicing: EN 16931 e-invoices (ZUGFeRD / Factur-X, XRechnung), '
               'PDF/A-3, VAT checks, archive with SHA-256, retention and legal hold',
    'author': 'Ähdus Technology',
    'website': 'https://ahdustechnology.com/',
    'category': 'Accounting/Localizations',
    'depends': [
        'account',
        'account_edi_ubl_cii',
        'account_edi_ubl_cii_tax_extension',
        'account_audit_trail',
        'l10n_din5008',
        'l10n_de',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/fsc_security.xml',
        'data/ir_cron.xml',
        'data/pdfa_metadata.xml',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'views/account_move_finance_form.xml',
        'views/fsc_gobd_views.xml',
        'report/report_invoice.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'finance_service_connector/static/src/scss/finance_form.scss',
        ],
    },
    'images': ['static/description/banner.png'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'OPL-1',
    'price': 9.0,
    'currency': 'EUR',
}
