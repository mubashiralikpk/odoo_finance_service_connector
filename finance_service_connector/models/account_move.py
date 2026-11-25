# -*- coding: utf-8 -*-
"""
German GoBD-compliant customer invoices.

Rules (mirrors Pitstop-CRM-tenant):
  1. Creation  - an invoice is issued only when the content required by §14 Abs. 4
                 UStG and EN 16931 is present (_fsc_compliance_issues).
  2. Saving    - at issue the PDF/A-3 (with embedded Factur-X XML) and the XML are
                 archived with SHA-256 hashes. Issued invoices cannot be reset,
                 edited or deleted; a correction is always a new document.
  3. Retention - 8 years from the end of the issue year (§14b UStG, §147 AO),
                 extendable per invoice, legal hold blocks any deletion.
  4. VAT       - every line carries exactly one VAT tax; 0 % needs an explicit
                 EN 16931 VAT category and, where required, a legal reason;
                 reverse charge / intra-EU need the buyer VAT ID.
  5. EN 16931  - see account_edi_xml_cii.py (Factur-X / ZUGFeRD EN16931 profile).
  6. PDF       - see account_move_send.py and report/report_invoice.xml.
"""
import io
import json
import logging
from datetime import date

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools.translate import code_translations

_logger = logging.getLogger(__name__)

# Same buckets as the Finance admin "Invoice type" picker
FS_INVOICE_TYPES = [
    ('MANUAL',         'Manual'),
    ('MEMBERSHIP',     'Membership'),
    ('SUBSCRIPTION',   'Subscription'),
    ('EVENT',          'Events'),
    ('ROOM_BOOKING',   'Room booking'),
    ('DRIVER_CREDITS', 'Driver credits'),
    ('POS_LEGAL',      'POS legal'),
    ('CORRECTION',     'Correction'),
    ('OTHER',          'Other'),
]

FS_SERVICE_TYPES = [
    ('delivery_date',      'Delivery date'),
    ('performance_date',   'Performance date'),
    ('delivery_period',    'Delivery period'),
    ('performance_period', 'Performance period'),
    ('none',               'Same as invoice date'),
]
PERIOD_SERVICE_TYPES = ('delivery_period', 'performance_period')

# §14b UStG / §147 AO retention classes -> minimum years
RETENTION_CLASSES = [
    ('ustg_14b',     'Invoice (§14b UStG / §147 AO) - 8 years'),
    ('ao_147_books', 'Books / annual accounts (§147 AO) - 10 years'),
    ('ustg_15a',     'Property-related (§14b Abs. 1 S. 5 UStG) - 10 years'),
    ('other_legal',  'Other legal obligation - 10 years'),
]
RETENTION_YEARS = {'ustg_14b': 8, 'ao_147_books': 10, 'ustg_15a': 10, 'other_legal': 10}

# Invoices up to this gross amount are "Kleinbetragsrechnungen" (§33 UStDV)
SMALL_AMOUNT_LIMIT = 250.0

# EN 16931 VAT categories
ZERO_RATE_CATEGORIES = {'Z', 'E', 'AE', 'K', 'G', 'O'}
REASON_REQUIRED = {'E', 'AE', 'K', 'G'}
BUYER_VAT_REQUIRED = {'AE', 'K'}
SELLER_VAT_REQUIRED = {'AE', 'K', 'G'}

# Statutory wording (§14a Abs. 5 S. 2 UStG) - the only text printed without
# the company configuring it on the tax.
STATUTORY_NOTE = {
    'AE': 'Steuerschuldnerschaft des Leistungsempfängers',
}

DEFAULT_TITLES = {'Invoice', 'Rechnung', 'Credit Note', 'Gutschrift', 'Rechnungskorrektur'}

# Content that is printed on the invoice / written to the XML. Locked once issued.
FSC_LOCKED_FIELDS = {
    'partner_id', 'invoice_date', 'delivery_date', 'narration', 'ref', 'payment_reference',
    'invoice_payment_term_id', 'invoice_date_due', 'currency_id', 'partner_bank_id',
    'fs_invoice_type', 'fs_service_type', 'fs_service_date_to', 'fs_buyer_reference',
    'fs_document_title', 'fs_intro_text', 'fs_payment_terms_text', 'fs_postscript',
    'fs_rcpt_street2', 'fs_rcpt_street', 'fs_rcpt_zip', 'fs_rcpt_city', 'fs_rcpt_country_id',
    'fs_rcpt_email', 'fs_rcpt_member_number', 'fsc_export_evidence_ref',
}




class AccountMove(models.Model):
    _inherit = 'account.move'

    # ── Finance form fields (mirror the Finance admin create/edit form) ───────
    fs_invoice_type = fields.Selection(
        FS_INVOICE_TYPES, string='Invoice type',
        default=lambda self: self._default_fs_invoice_type(), copy=False,
    )
    fs_service_type = fields.Selection(
        FS_SERVICE_TYPES, string='Delivery / service type', default='delivery_date',
    )
    fs_service_date_to = fields.Date(string='Service period end')
    fs_buyer_reference = fields.Char(string='Buyer reference / Leitweg-ID')
    fs_document_title = fields.Char(string='Document title', default=lambda self: _('Invoice'))
    fs_intro_text = fields.Text(string='Introductory text')
    fs_payment_terms_text = fields.Text(string='Payment terms')
    fs_postscript = fields.Text(string='Postscript')
    fsc_export_evidence_ref = fields.Char(
        string='Export evidence reference',
        help='Required for VAT category G (export outside the EU): customs / '
             'Ausfuhrnachweis reference.')

    # Recipient snapshot — filled from the customer, editable per invoice until
    # it is issued (the customer record itself is not changed).
    fs_rcpt_street2 = fields.Char(
        string='Address supplement', compute='_compute_fs_recipient',
        store=True, readonly=False, precompute=True)
    fs_rcpt_street = fields.Char(
        string='Street and house number', compute='_compute_fs_recipient',
        store=True, readonly=False, precompute=True)
    fs_rcpt_zip = fields.Char(
        string='Postcode', compute='_compute_fs_recipient',
        store=True, readonly=False, precompute=True)
    fs_rcpt_city = fields.Char(
        string='City', compute='_compute_fs_recipient',
        store=True, readonly=False, precompute=True)
    fs_rcpt_country_id = fields.Many2one(
        'res.country', string='Country', compute='_compute_fs_recipient',
        store=True, readonly=False, precompute=True)
    fs_rcpt_email = fields.Char(
        string='Email', compute='_compute_fs_recipient',
        store=True, readonly=False, precompute=True)
    fs_rcpt_member_number = fields.Char(
        string='Member number', compute='_compute_fs_recipient',
        store=True, readonly=False, precompute=True)

    # ── GoBD state ────────────────────────────────────────────────────────────
    fsc_is_gobd_document = fields.Boolean(compute='_compute_fsc_is_gobd_document')
    fsc_issued_at = fields.Datetime(string='Issued at', readonly=True, copy=False)
    fsc_issued_by_id = fields.Many2one('res.users', string='Issued by', readonly=True, copy=False)
    fsc_retention_class = fields.Selection(
        RETENTION_CLASSES, string='Retention class', default='ustg_14b',
        readonly=True, copy=False)
    fsc_retention_extra_years = fields.Integer(string='Extra retention years', readonly=True, copy=False)
    fsc_retention_until = fields.Date(
        string='Retain until', compute='_compute_fsc_retention_until', store=True,
        help='End of the issue year + the legal retention period (+ extra years). '
             'Deletion is not possible before this date or while a legal hold is active.')
    fsc_legal_hold = fields.Boolean(string='Legal hold', readonly=True, copy=False)
    fsc_legal_hold_reason = fields.Text(string='Legal hold reason', readonly=True, copy=False)
    fsc_legal_hold_until = fields.Date(string='Legal hold until', readonly=True, copy=False)
    fsc_archive_ids = fields.One2many('fsc.invoice.archive', 'move_id', string='Archived documents')
    fsc_archive_state = fields.Selection([
        ('none', 'Not issued'),
        ('pending', 'Pending'),
        ('archived', 'Archived'),
        ('failed', 'Integrity failed'),
    ], string='GoBD archive', default='none', readonly=True, copy=False)
    fsc_audit_event_ids = fields.One2many('fsc.audit.event', 'move_id', string='Audit log')
    fsc_compliance_issues = fields.Text(
        string='Missing for issue', compute='_compute_fsc_compliance_issues')
    fsc_legal_statements = fields.Text(compute='_compute_fsc_legal_statements')

    # ─────────────────────────────────────────────────────────────────────────
    # Defaults / computes
    # ─────────────────────────────────────────────────────────────────────────
    @api.model
    def _default_fs_invoice_type(self):
        if self.env.context.get('default_move_type') == 'out_refund':
            return 'CORRECTION'
        return 'MANUAL'

    @api.depends('partner_id')
    def _compute_fs_recipient(self):
        # partner_id is locked once issued, so the snapshot cannot change afterwards
        for move in self:
            p = move.partner_id
            move.fs_rcpt_street2 = p.street2
            move.fs_rcpt_street = p.street
            move.fs_rcpt_zip = p.zip
            move.fs_rcpt_city = p.city
            move.fs_rcpt_country_id = p.country_id
            move.fs_rcpt_email = p.email
            move.fs_rcpt_member_number = p.ref

    @api.depends('move_type')
    def _compute_fsc_is_gobd_document(self):
        for move in self:
            move.fsc_is_gobd_document = move.move_type in ('out_invoice', 'out_refund')

    @api.depends('fsc_issued_at', 'invoice_date', 'fsc_retention_class',
                 'fsc_retention_extra_years', 'company_id.fsc_retention_years')
    def _compute_fsc_retention_until(self):
        for move in self:
            if not move.fsc_issued_at:
                move.fsc_retention_until = False
                continue
            issue_year = (move.invoice_date or move.fsc_issued_at.date()).year
            years = max(
                RETENTION_YEARS.get(move.fsc_retention_class or 'ustg_14b', 8),
                move.company_id.fsc_retention_years or 8,
            ) + max(0, move.fsc_retention_extra_years or 0)
            move.fsc_retention_until = date(issue_year + years, 12, 31)

    @api.depends('state', 'move_type', 'partner_id', 'invoice_line_ids.tax_ids',
                 'invoice_line_ids.display_type', 'invoice_line_ids.name',
                 'fs_rcpt_street', 'fs_rcpt_zip', 'fs_rcpt_city', 'fs_rcpt_country_id',
                 'fs_service_type', 'delivery_date', 'fs_service_date_to',
                 'fs_invoice_type', 'fs_buyer_reference', 'fsc_export_evidence_ref',
                 'partner_bank_id', 'amount_total', 'reversed_entry_id')
    def _compute_fsc_compliance_issues(self):
        for move in self:
            if move.state != 'draft' or not move.fsc_is_gobd_document:
                move.fsc_compliance_issues = False
                continue
            issues = move._fsc_compliance_issues()
            move.fsc_compliance_issues = '\n'.join(f'• {msg}' for msg in issues) or False

    @api.depends('invoice_line_ids.tax_ids', 'reversed_entry_id', 'partner_id.vat')
    def _compute_fsc_legal_statements(self):
        for move in self:
            move.fsc_legal_statements = '\n'.join(move._fsc_legal_statement_lines()) or False

    # ─────────────────────────────────────────────────────────────────────────
    # 1 + 4. Creation and VAT rules
    # ─────────────────────────────────────────────────────────────────────────
    def _fsc_tax_category(self, tax):
        """EN 16931 VAT category of a tax. Never guessed for 0 %: Odoo would
        silently call it 'E'; Pitstop and GoBD require an explicit choice."""
        cat = tax.ubl_cii_tax_category_code
        if cat:
            return cat
        return 'S' if tax.amount else False

    def _fsc_eu_country_codes(self):
        return set(self.env.ref('base.europe').country_ids.mapped('code'))

    def _fsc_buyer_country(self):
        self.ensure_one()
        return self.fs_rcpt_country_id or self.partner_id.country_id

    def _fsc_billable_lines(self):
        return self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')

    def _fsc_edi_format(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        return 'ubl_cii_format' in partner._fields and partner.ubl_cii_format or False

    def _fsc_compliance_issues(self):
        """All reasons why this customer invoice may not be issued yet.
        Returns a list of messages (empty = ready)."""
        self.ensure_one()
        issues = []
        company = self.company_id
        seller = company.partner_id
        buyer = self.partner_id
        commercial = buyer.commercial_partner_id
        lines = self._fsc_billable_lines()

        # -- Seller (§14 Abs. 4 Nr. 1 + 2 UStG, EN 16931 BR-06/BR-08/BR-09)
        if not all([seller.name, seller.street, seller.zip, seller.city, seller.country_id]):
            issues.append(_('Your company address is incomplete (name, street, postcode, city, '
                            'country) - §14 Abs. 4 Nr. 1 UStG.'))
        if not (company.vat or company.fsc_tax_number):
            issues.append(_('Your company needs a VAT ID (USt-IdNr.) or a tax number (Steuernummer) '
                            '- §14 Abs. 4 Nr. 2 UStG. Set it in Settings → Invoicing → GoBD.'))
        if not (company.vat or company.company_registry):
            issues.append(_('Without a VAT ID the e-invoice needs your company register number '
                            '(Handelsregister / Vereinsregister, e.g. "HRB 12345" or "VR 1234") - EN 16931 BR-CO-26. '
                            'Set it as Company ID in Settings → Companies, or add the VAT ID.'))
        if not (seller.phone or seller.mobile):
            issues.append(_('Your company needs a phone number on the e-invoice (BR-DE-6): Settings → Companies.'))
        if not company.email:
            issues.append(_('Your company needs an email address on the e-invoice (BR-DE-7): Settings → Companies.'))

        # -- Buyer (§14 Abs. 4 Nr. 1 UStG, EN 16931 BR-07 / BR-11)
        if not buyer:
            issues.append(_('Choose the member / customer.'))
        country = self._fsc_buyer_country()
        if buyer and not country:
            issues.append(_('The member country is missing (EN 16931 BR-11).'))
        small_amount = (
            self.move_type == 'out_invoice'
            and self.currency_id == company.currency_id
            and company.currency_id.name == 'EUR'
            and self.amount_total <= SMALL_AMOUNT_LIMIT
        )
        missing_addr = [label for label, value in (
            (_('street'), self.fs_rcpt_street),
            (_('postcode'), self.fs_rcpt_zip),
            (_('city'), self.fs_rcpt_city),
        ) if not value]
        edi_format = self._fsc_edi_format()
        if buyer and missing_addr and not small_amount:
            issues.append(_('The member address is incomplete - add the missing %(fields)s '
                            '(§14 Abs. 4 Nr. 1 UStG; only invoices up to 250 € gross may omit it, '
                            '§33 UStDV).', fields=', '.join(missing_addr)))
        if edi_format == 'xrechnung':
            if not self.fs_buyer_reference:
                issues.append(_('XRechnung customers need the buyer reference / Leitweg-ID (BR-DE-15).'))
            if (self.fs_rcpt_street, self.fs_rcpt_zip, self.fs_rcpt_city, self.fs_rcpt_country_id) != (
                    commercial.street, commercial.zip, commercial.city, commercial.country_id):
                issues.append(_('For XRechnung customers the address comes from the customer record. '
                                'Edit the customer instead of this invoice.'))
        if self.move_type == 'out_invoice' and edi_format in ('zugferd', 'facturx', 'xrechnung') \
                and not self.partner_bank_id:
            issues.append(_('Choose your bank account (Recipient Bank on the Other Info tab): '
                            'the e-invoice needs payment instructions (BR-DE-1).'))
        if self.move_type == 'out_invoice' and self.partner_bank_id and not self.partner_bank_id.allow_out_payment:
            issues.append(_('Your bank account %s is not trusted yet: open it in the bank settings and '
                            'click "Send Money" to trust it.', self.partner_bank_id.display_name))

        # -- Delivery / service date (§14 Abs. 4 Nr. 6 UStG)
        if self.fs_service_type in PERIOD_SERVICE_TYPES:
            if not self.delivery_date or not self.fs_service_date_to:
                issues.append(_('Enter the start and end of the service period.'))
            elif self.fs_service_date_to < self.delivery_date:
                issues.append(_('The service period ends before it starts.'))

        # -- Correction
        if self.fs_invoice_type == 'CORRECTION':
            if self.move_type == 'out_invoice':
                issues.append(_('A correction is issued as a credit note: open the original invoice '
                                'and click "Credit Note".'))
            elif not self.reversed_entry_id:
                issues.append(_('A correction must reference the original invoice. Create it with '
                                '"Credit Note" from the original invoice.'))

        # -- Lines (§14 Abs. 4 Nr. 5 UStG, EN 16931 BR-CO-04)
        if not lines:
            issues.append(_('Add at least one article line.'))
        categories = set()
        for line in lines:
            label = (line.name or line.product_id.display_name or _('Line %s', line.sequence)).splitlines()[0]
            if not (line.name or '').strip():
                issues.append(_('Line "%s" needs a description.', label))
            vat_taxes = line.tax_ids.filtered(lambda t: t.amount_type in ('percent', 'division'))
            if len(vat_taxes) != 1:
                issues.append(_('Line "%s" must have exactly one VAT tax (EN 16931 BR-CO-04).', label))
                continue
            tax = vat_taxes
            cat = self._fsc_tax_category(tax)
            if not cat:
                issues.append(_('Line "%(line)s": the 0%% tax "%(tax)s" has no VAT category. Set the Tax '
                                'Category Code (Z, E, AE, K or G) on the tax.', line=label, tax=tax.name))
                continue
            categories.add(cat)
            if tax.amount and cat != 'S':
                issues.append(_('Tax "%(tax)s" has %(rate)s %% but category %(cat)s - categories '
                                'Z/E/AE/K/G/O must be 0 %%.', tax=tax.name, rate=tax.amount, cat=cat))
            if not tax.amount and cat == 'S':
                issues.append(_('Tax "%s" is 0 %% but category S (standard rate).', tax.name))
            if cat in REASON_REQUIRED and not (tax.ubl_cii_tax_exemption_reason_code or tax.fsc_legal_note):
                issues.append(_('Tax "%(tax)s" (category %(cat)s) needs an exemption reason code or '
                                'a legal note.', tax=tax.name, cat=cat))
            if cat == 'Z' and tax.ubl_cii_tax_exemption_reason_code:
                issues.append(_('Tax "%s" is zero-rated (Z) and must not carry an exemption '
                                'reason (EN 16931 BR-Z-10).', tax.name))
            if cat == 'O':
                issues.append(_('Tax "%s" is "outside the scope of VAT" (O). Such amounts are not VAT '
                                'invoices and cannot be issued as EN 16931 e-invoices.', tax.name))

        eu = self._fsc_eu_country_codes()
        if categories & BUYER_VAT_REQUIRED and not commercial.vat:
            issues.append(_('Reverse charge / intra-EU supply needs the member\'s VAT ID (USt-IdNr.).'))
        if categories & SELLER_VAT_REQUIRED and not company.vat:
            issues.append(_('Reverse charge, intra-EU and export invoices need your company VAT ID '
                            '(BR-AE-02 / BR-IC-02 / BR-G-02).'))
        if 'K' in categories and country and (
                country.code not in eu or country == seller.country_id):
            issues.append(_('An intra-community supply (K) needs a member in another EU country.'))
        if 'G' in categories:
            if country and country.code in eu:
                issues.append(_('An export (G) needs a member outside the EU.'))
            if not self.fsc_export_evidence_ref:
                issues.append(_('An export (G) needs the export evidence reference (Ausfuhrnachweis).'))
        return issues

    def _fsc_assert_ready_to_issue(self):
        problems = []
        for move in self.filtered('fsc_is_gobd_document'):
            issues = move._fsc_compliance_issues()
            if issues:
                problems.append('%s\n%s' % (
                    move.name if move.name and move.name != '/' else move.partner_id.display_name or _('Invoice'),
                    '\n'.join(f'  • {i}' for i in issues)))
        if problems:
            raise UserError(_('This invoice cannot be issued yet (GoBD / §14 UStG / EN 16931):\n\n%s',
                              '\n\n'.join(problems)))

    def _fsc_assert_einvoice_buildable(self):
        """Run Odoo's own EN 16931 constraints so posting fails with a clear
        message instead of producing a document without e-invoice."""
        errors = []
        for move in self.filtered('fsc_is_gobd_document'):
            builders = [self.env['account.edi.xml.cii']]
            if move._fsc_edi_format() == 'xrechnung':
                builders.append(self.env['account.edi.xml.ubl_de'])
            for builder in builders:
                _xml, builder_errors = builder._export_invoice(move)
                errors += [f'{move.name}: {e}' for e in builder_errors]
        if errors:
            raise UserError(_('The EN 16931 e-invoice cannot be built:\n\n%s', '\n'.join(sorted(set(errors)))))

    # ─────────────────────────────────────────────────────────────────────────
    # PDF helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _fsc_legal_statement_lines(self):
        """VAT and correction statements printed on the PDF (§14 Abs. 4 Nr. 8,
        §14a UStG). Wording comes from the tax configuration; only the statutory
        reverse-charge phrase is built in."""
        self.ensure_one()
        lines = []
        seen = set()
        for line in self._fsc_billable_lines():
            for tax in line.tax_ids:
                cat = self._fsc_tax_category(tax)
                if cat not in REASON_REQUIRED or tax.id in seen:
                    continue
                seen.add(tax.id)
                text = tax.fsc_legal_note or STATUTORY_NOTE.get(cat)
                if not text and tax.description and tax.description != tax.name:
                    text = tax.description  # e.g. "Steuerfreie Ausfuhr (§4 Nr. 1a UStG)" from l10n_de
                if not text and tax.ubl_cii_tax_exemption_reason_code:
                    text = dict(tax._fields['ubl_cii_tax_exemption_reason_code']._description_selection(self.env)).get(
                        tax.ubl_cii_tax_exemption_reason_code)
                if text:
                    lines.append(text)
                if cat in BUYER_VAT_REQUIRED and self.partner_id.commercial_partner_id.vat:
                    lines.append(_('VAT ID of the recipient: %s', self.partner_id.commercial_partner_id.vat))
                if cat == 'G' and self.fsc_export_evidence_ref:
                    lines.append(_('Export evidence: %s', self.fsc_export_evidence_ref))
        if self.move_type == 'out_refund' and self.reversed_entry_id:
            original = self.reversed_entry_id
            lines.append(_('This document corrects invoice %(name)s dated %(date)s.',
                           name=original.name,
                           date=tools.format_date(self.env, original.invoice_date)))
        return lines

    def _compute_l10n_din5008_template_data(self):
        # DIN 5008 info box: service date / period, member number, buyer reference
        super()._compute_l10n_din5008_template_data()
        for move in self.filtered('fsc_is_gobd_document'):
            lang = self.env.lang or 'en_US'
            din_labels = code_translations.get_python_translations('l10n_din5008', lang)
            delivery_labels = {'Delivery Date', din_labels.get('Delivery Date', 'Delivery Date')}
            data = [row for row in (move.l10n_din5008_template_data or []) if row[0] not in delivery_labels]
            if move.delivery_date:
                value = tools.format_date(self.env, move.delivery_date)
                if move.fs_service_date_to:
                    value += ' – ' + tools.format_date(self.env, move.fs_service_date_to)
                data.append((move._fsc_service_date_label(), value))
            if move.fs_rcpt_member_number:
                data.append((_('Member number'), move.fs_rcpt_member_number))
            if move.fs_buyer_reference:
                data.append((_('Buyer reference'), move.fs_buyer_reference))
            move.l10n_din5008_template_data = data

    def _compute_l10n_din5008_document_title(self):
        # DIN 5008 title = the document title of the invoice; never "Gutschrift" for a correction
        super()._compute_l10n_din5008_document_title()
        for move in self.filtered(lambda m: m.fsc_is_gobd_document and m.state == 'posted'):
            move.l10n_din5008_document_title = move._fsc_document_title()

    def _fsc_document_title(self):
        """Title printed on the PDF, in the document's language (the report renders
        with the customer's language). A title the user typed is kept as is; the
        default titles follow the language. Corrections are never "Gutschrift"
        (§14 Abs. 4 Nr. 10 UStG reserves it for self-billing)."""
        self.ensure_one()
        title = (self.fs_document_title or '').strip()
        if title and title not in DEFAULT_TITLES:
            return title
        return _('Credit Note') if self.move_type == 'out_refund' else _('Invoice')

    def _fsc_service_date_label(self):
        self.ensure_one()
        return dict(self._fields['fs_service_type']._description_selection(self.env)).get(
            self.fs_service_type) or _('Delivery date')

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Saving: issue, archive, immutability
    # ─────────────────────────────────────────────────────────────────────────
    def _post(self, soft=True):
        gobd = self.filtered(lambda m: m.fsc_is_gobd_document and m.state == 'draft')
        gobd._fsc_assert_ready_to_issue()
        for move in gobd:
            if not move.delivery_date or move.fs_service_type == 'none':
                move.delivery_date = move.invoice_date or fields.Date.context_today(move)
            if move.fs_service_type not in PERIOD_SERVICE_TYPES and move.fs_service_date_to:
                move.fs_service_date_to = False
        posted = super()._post(soft=soft)
        issued = posted.filtered(lambda m: m.fsc_is_gobd_document and not m.fsc_issued_at)
        if issued:
            issued._fsc_assert_einvoice_buildable()
            issued._fsc_mark_issued()
        return posted

    def _fsc_mark_issued(self):
        now = fields.Datetime.now()
        for move in self:
            move.with_context(fsc_system_write=True).write({
                'fsc_issued_at': now,
                'fsc_issued_by_id': self.env.user.id,
                'fsc_archive_state': 'pending',
            })
            move._fsc_log('issued', new={
                'name': move.name,
                'invoice_date': str(move.invoice_date),
                'partner': move.partner_id.display_name,
                'currency': move.currency_id.name,
                'amount_untaxed': move.amount_untaxed,
                'amount_tax': move.amount_tax,
                'amount_total': move.amount_total,
                'retention_until': str(move.fsc_retention_until),
            })
            if move.move_type == 'out_refund' and move.reversed_entry_id:
                move.reversed_entry_id._fsc_log('correction', new={
                    'credit_note': move.name, 'amount_total': move.amount_total})
        if not self.env.context.get('fsc_skip_documents'):
            self._fsc_generate_and_archive()

    def _fsc_generate_and_archive(self):
        """Render the official PDF/A-3 (+ XML) once and archive it. Failures do
        not undo the posting: the invoice stays 'pending' and the daily job
        retries."""
        send = self.env['account.move.send']
        for move in self:
            if move.fsc_archive_state == 'archived':
                continue
            if not move.invoice_pdf_report_id:
                was_sent = move.is_move_sent
                invoice_data = {'ubl_cii_xml': True}
                try:
                    with self.env.cr.savepoint():
                        send._generate_invoice_documents({move: invoice_data})
                        if invoice_data.get('error') and not move.invoice_pdf_report_id:
                            raise UserError(str(invoice_data['error']))
                except Exception as e:  # noqa: BLE001 - keep posting, retry later
                    _logger.warning('GoBD: documents for %s could not be generated: %s', move.name, e)
                    move._fsc_log('archive_failed', reason=str(e)[:2000])
                    continue
                if not was_sent:
                    move.sudo().is_move_sent = False
            move._fsc_archive_documents()

    def _fsc_archive_documents(self):
        self.ensure_one()
        Archive = self.env['fsc.invoice.archive'].sudo()
        archived_attachments = self.fsc_archive_ids.attachment_id
        to_archive = []
        pdf = self.invoice_pdf_report_id
        if pdf and pdf not in archived_attachments:
            to_archive.append(('pdf', pdf, 'PDF/A-3 + Factur-X EN 16931'))
            xml_raw = self._fsc_extract_facturx(pdf.raw)
            if xml_raw:
                xml_att = self.env['ir.attachment'].sudo().create({
                    'name': '%s_factur-x.xml' % self.name.replace('/', '_'),
                    'raw': xml_raw,
                    'mimetype': 'application/xml',
                    'res_model': self._name,
                    'res_id': self.id,
                })
                to_archive.append(('xml', xml_att, 'Factur-X / ZUGFeRD EN 16931 (CII)'))
        ubl = 'ubl_cii_xml_id' in self._fields and self.ubl_cii_xml_id
        if ubl and ubl not in archived_attachments and self._fsc_edi_format() not in ('zugferd', 'facturx'):
            to_archive.append(('xml', ubl, dict(
                self.partner_id.commercial_partner_id._fields['ubl_cii_format']._description_selection(self.env)
            ).get(self._fsc_edi_format(), 'UBL')))
        if not to_archive and not self.fsc_archive_ids:
            return
        records = Archive.browse()
        for kind, attachment, standard in to_archive:
            records |= Archive.create({
                'move_id': self.id,
                'kind': kind,
                'standard': standard,
                'attachment_id': attachment.id,
            })
        self.with_context(fsc_system_write=True).fsc_archive_state = 'archived'
        if records:
            self._fsc_log('archived', new={r.filename: r.sha256 for r in records})

    @api.model
    def _fsc_extract_facturx(self, pdf_raw):
        from odoo.tools.pdf import OdooPdfFileReader
        try:
            reader = OdooPdfFileReader(io.BytesIO(pdf_raw), strict=False)
            for name, content in reader.getAttachments():
                if name in ('factur-x.xml', 'zugferd-invoice.xml', 'xrechnung.xml'):
                    return content
        except Exception as e:  # noqa: BLE001
            _logger.warning('GoBD: could not read embedded XML: %s', e)
        return None

    def write(self, vals):
        if not self.env.context.get('fsc_system_write'):
            locked = FSC_LOCKED_FIELDS.intersection(vals)
            if locked:
                issued = self.filtered(lambda m: m.fsc_issued_at and m.fsc_is_gobd_document)
                if issued:
                    names = ', '.join(issued.mapped('name'))
                    fields_desc = ', '.join(sorted(self._fields[f].string for f in locked if f in self._fields))
                    raise UserError(_(
                        'GoBD: %(names)s has been issued and can no longer be changed (%(fields)s). '
                        'Create a credit note to correct it.', names=names, fields=fields_desc))
        return super().write(vals)

    def button_draft(self):
        issued = self.filtered(lambda m: m.fsc_is_gobd_document and m.fsc_issued_at)
        if issued:
            self.env['fsc.audit.event']._log_outside_transaction(
                issued, 'reset_blocked', reason=_('Reset to draft refused'))
            raise UserError(_(
                'GoBD: %s has been issued and cannot be reset to draft. '
                'To correct or cancel it, click "Credit Note" (Gutschrift / Rechnungskorrektur).',
                ', '.join(issued.mapped('name'))))
        return super().button_draft()

    def button_cancel(self):
        issued = self.filtered(lambda m: m.fsc_is_gobd_document and m.fsc_issued_at)
        if issued:
            raise UserError(_(
                'GoBD: %s has been issued. Cancel it with a credit note ("Credit Note" button).',
                ', '.join(issued.mapped('name'))))
        return super().button_cancel()

    def unlink(self):
        self._fsc_check_unlink()
        return super().unlink()

    def _fsc_check_unlink(self):
        protected = self.filtered(lambda m: m.fsc_is_gobd_document and (m.fsc_issued_at or m.posted_before))
        if protected:
            self.env['fsc.audit.event']._log_outside_transaction(
                protected, 'hard_delete_blocked', reason=_('Delete refused'))
            raise UserError(_(
                'GoBD: issued invoices are kept for the legal retention period and cannot be deleted '
                '(%s).', ', '.join(protected.mapped('name'))))

    def _fsc_log(self, event_type, reason=None, old=None, new=None):
        self.ensure_one()
        return self.env['fsc.audit.event'].sudo().create({
            'company_id': self.company_id.id,
            'move_id': self.id,
            'event_type': event_type,
            'reason': reason,
            'old_value': json.dumps(old, default=str, sort_keys=True) if old is not None else False,
            'new_value': json.dumps(new, default=str, sort_keys=True) if new is not None else False,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Retention: legal hold + integrity
    # ─────────────────────────────────────────────────────────────────────────
    def action_fsc_open_legal_hold(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Legal hold / retention'),
            'res_model': 'fsc.legal.hold.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def action_fsc_verify_integrity(self):
        failed = self.fsc_archive_ids._fsc_verify()
        if failed:
            raise UserError(_('Integrity check FAILED for: %s', ', '.join(failed.mapped('filename'))))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Integrity OK'),
                'message': _('%s archived document(s) match their SHA-256 hash.', len(self.fsc_archive_ids)),
            },
        }

    def action_fsc_archive_now(self):
        self.filtered(lambda m: m.state == 'posted' and m.fsc_issued_at)._fsc_generate_and_archive()

    @api.model
    def _fsc_adopt_existing_invoices(self):
        """Invoices posted before this module was installed are issued documents
        too: lock them, start their retention and archive their PDF."""
        moves = self.sudo().search([
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'), ('fsc_issued_at', '=', False)])
        for move in moves:
            move.with_context(fsc_system_write=True).write({
                'fsc_issued_at': move.create_date,
                'fsc_issued_by_id': move.create_uid.id,
                'fsc_archive_state': 'pending',
            })
            move._fsc_log('issued', reason='Adopted when GoBD rules were installed', new={
                'name': move.name, 'amount_total': move.amount_total,
                'retention_until': str(move.fsc_retention_until)})
        return moves

    @api.model
    def _cron_fsc_gobd_maintenance(self):
        pending = self.search([
            ('fsc_archive_state', '=', 'pending'), ('state', '=', 'posted')], limit=200)
        pending._fsc_generate_and_archive()
        self.env['fsc.invoice.archive'].search([])._fsc_verify()
        for company in self.env['res.company'].search([]):
            broken = self.env['fsc.audit.event'].sudo()._verify_chain(company)
            if broken:
                _logger.error('GoBD: audit log chain broken for %s at event %s', company.name, broken.id)

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle hooks
    # ─────────────────────────────────────────────────────────────────────────
    def _reverse_moves(self, default_values_list=None, cancel=False):
        if default_values_list is None:
            default_values_list = [{} for _move in self]
        for move, vals in zip(self, default_values_list):
            vals.setdefault('fs_invoice_type', 'CORRECTION')
            # printed via _fsc_document_title(): "Credit Note" / "Rechnungskorrektur"
            vals.setdefault('fs_document_title', _('Credit Note'))
            vals.setdefault('fs_service_type', move.fs_service_type)
            vals.setdefault('fs_buyer_reference', move.fs_buyer_reference)
            vals.setdefault('delivery_date', move.delivery_date)
            vals.setdefault('fs_service_date_to', move.fs_service_date_to)
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)

    def _invoice_paid_hook(self):
        result = super()._invoice_paid_hook()
        for move in self.filtered('fsc_issued_at'):
            move._fsc_log('payment_linked', new={
                'payment_state': move.payment_state, 'amount_residual': move.amount_residual})
        return result
