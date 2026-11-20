# -*- coding: utf-8 -*-
"""
Extends account.move (Odoo invoices) with Finance Service sync fields and logic.

Flow:
  1. User confirms invoice → action_post() → auto-sync if enabled
  2. OR user clicks "Sync to Finance Service" button manually
  3. POST /tenants/:id/invoices  → stores returned finance_service_id
  4. When payment registered → PATCH status to PAID
"""
import json
import logging
import urllib.error
import urllib.request
from datetime import date

from odoo import api, fields, models
from odoo.tools import is_html_empty
from odoo.tools.mail import html_to_inner_content
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MOVE_TYPE_TO_DOC_TYPE = {
    'out_invoice': 'INVOICE',
    'out_refund':  'CREDIT_NOTE',
    'in_invoice':  'INVOICE',
    'in_refund':   'CREDIT_NOTE',
}

# Same buckets as the Finance Service admin "Invoice type" picker
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
    ('none',               'No delivery date'),
]

SYNC_STATE_SELECTION = [
    ('not_synced', 'Not Synced'),
    ('synced',     'Synced'),
    ('error',      'Error'),
]


def _clean(values):
    """Drop Odoo empty values (False / None / '') so they are not sent as JSON false/null."""
    return {k: v for k, v in values.items() if v is not None and v is not False and v != ''}


class AccountMove(models.Model):
    _inherit = 'account.move'

    fs_invoice_id = fields.Char(
        string='Finance Service ID',
        readonly=True, copy=False,
        help='UUID of this invoice in the Finance Service',
    )
    fs_invoice_number = fields.Char(
        string='FS Invoice Number',
        readonly=True, copy=False,
    )
    fs_sync_state = fields.Selection(
        selection=SYNC_STATE_SELECTION,
        string='Sync Status',
        default='not_synced',
        readonly=True, copy=False,
    )
    fs_sync_error = fields.Text(
        string='Sync Error',
        readonly=True, copy=False,
    )
    fs_synced_at = fields.Datetime(
        string='Last Synced',
        readonly=True, copy=False,
    )

    # ── Finance form fields (mirror the Finance Service create/edit form) ─────
    fs_invoice_type = fields.Selection(
        FS_INVOICE_TYPES, string='Invoice type',
        default=lambda self: self._default_fs_invoice_type(),
    )
    fs_service_type = fields.Selection(
        FS_SERVICE_TYPES, string='Delivery / service type', default='delivery_date',
    )
    fs_buyer_reference = fields.Char(string='Buyer reference / Leitweg-ID')
    fs_document_title = fields.Char(string='Document title', default='Invoice')
    fs_intro_text = fields.Text(string='Introductory text')
    fs_payment_terms_text = fields.Text(string='Payment terms')
    fs_postscript = fields.Text(string='Postscript')

    # Recipient snapshot — filled from the customer, editable per invoice
    # (the customer record itself is not changed).
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

    @api.model
    def _default_fs_invoice_type(self):
        if self.env.context.get('default_move_type') == 'out_refund':
            return 'CORRECTION'
        return 'MANUAL'

    @api.depends('partner_id')
    def _compute_fs_recipient(self):
        for move in self:
            p = move.partner_id
            move.fs_rcpt_street2 = p.street2
            move.fs_rcpt_street = p.street
            move.fs_rcpt_zip = p.zip
            move.fs_rcpt_city = p.city
            move.fs_rcpt_country_id = p.country_id
            move.fs_rcpt_email = p.email
            move.fs_rcpt_member_number = p.ref

    def _reverse_moves(self, default_values_list=None, cancel=False):
        # Credit notes are "Correction" invoices in the Finance Service
        if default_values_list is None:
            default_values_list = [{} for _ in self]
        for vals in default_values_list:
            vals.setdefault('fs_invoice_type', 'CORRECTION')
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fs_get_config(self):
        """Return (url, api_key, tenant_id, auto_sync) from the invoice's company."""
        self.ensure_one()
        company = self.company_id or self.env.company
        url       = (company.fs_api_url or '').rstrip('/')
        api_key   = company.fs_api_key or ''
        tenant_id = company.fs_tenant_id or ''
        auto_sync = company.fs_auto_sync
        return url, api_key, tenant_id, auto_sync

    def _fs_build_payload(self):
        """Convert this account.move to a CreateInvoiceDto dict."""
        self.ensure_one()
        move = self
        partner = move.partner_id

        # Odoo uses False for empty fields — _clean() drops False / None / '' so
        # the Finance Service only receives real strings.
        company_name = partner.commercial_company_name or ''
        country = move.fs_rcpt_country_id or partner.country_id
        recipient = _clean({
            'name':              partner.name or partner.display_name or 'Unknown',
            'email':             move.fs_rcpt_email,
            'taxId':             partner.vat,
            'companyName':       company_name if company_name != partner.name else None,
            'addressSupplement': move.fs_rcpt_street2,
            'addressLine1':      move.fs_rcpt_street,
            'city':              move.fs_rcpt_city,
            'postalCode':        move.fs_rcpt_zip,
            'country':           country.code if country else None,
            'memberNumber':      move.fs_rcpt_member_number,
        })

        line_items = []
        for line in move.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
        ):
            tax_rate = sum(
                t.amount for t in line.tax_ids if t.amount_type == 'percent'
            ) if line.tax_ids else 0.0
            line_items.append({
                'description': line.name or (line.product_id.name if line.product_id else 'Item'),
                'quantity':    float(line.quantity),
                'unitPrice':   float(line.price_unit),
                'taxRate':     float(tax_rate),
                'discount':    float(line.discount) if line.discount else 0.0,
            })

        def _fmt(d):
            return d.strftime('%Y-%m-%dT00:00:00.000Z') if isinstance(d, date) else None

        payload = _clean({
            'source':            'odoo',
            'externalId':        str(move.id),
            'externalRef':       f'odoo-{move.company_id.id}-{move.id}',
            'docType':           ('CANCELLATION'
                                  if move.fs_invoice_type == 'CORRECTION' and move.move_type == 'out_invoice'
                                  else MOVE_TYPE_TO_DOC_TYPE.get(move.move_type, 'INVOICE')),
            'isCancellation':    (move.move_type in ('out_refund', 'in_refund')
                                  or move.fs_invoice_type == 'CORRECTION'),
            'currency':          move.currency_id.name or 'EUR',
            'locale':            (move.partner_id.lang or 'en').split('_')[0],
            'recipientSnapshot': recipient,
            'lineItems':         line_items,
            'issueDate':         _fmt(move.invoice_date),
            'dueDate':           _fmt(move.invoice_date_due),
            'invoiceNumber':     move.name if move.name and move.name != '/' else None,
            'invoiceType':       move.fs_invoice_type or 'MANUAL',
            'title':             move.fs_document_title,
            'introText':         move.fs_intro_text,
            'paymentTerms':      move.fs_payment_terms_text or (
                                     move.invoice_payment_term_id.name
                                     if move.invoice_payment_term_id else None),
            'postscript':        move.fs_postscript,
            'notes':             (html_to_inner_content(move.narration)
                                  if move.narration and not is_html_empty(move.narration) else None),
            'buyerReference':    move.fs_buyer_reference,
            'deliveryDate':      (_fmt(move.delivery_date or move.invoice_date)
                                  if move.fs_service_type != 'none' else None),
            'metadata': {
                'odoo_move_id':   move.id,
                'odoo_move_type': move.move_type,
                'odoo_name':      move.name,
                'odoo_journal':   move.journal_id.name,
                'odoo_company':   move.company_id.name,
                'serviceType':    move.fs_service_type,
            },
        })
        return payload

    def _fs_request(self, method, path, data=None):
        """Low-level HTTP call. Returns parsed JSON. Raises UserError on failure."""
        url, api_key, tenant_id, _ = self._fs_get_config()
        if not url or not api_key or not tenant_id:
            raise UserError(
                'Finance Service is not configured. '
                'Go to Accounting → Settings → Finance Service.'
            )

        full_url = f'{url}/api/v1/{path.lstrip("/")}'
        body = json.dumps(data).encode('utf-8') if data else None
        req = urllib.request.Request(
            full_url, data=body, method=method,
            headers={
                'Content-Type': 'application/json',
                'Accept':       'application/json',
                'x-api-key':    api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode('utf-8')
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode('utf-8', errors='replace')
            try:
                detail = json.loads(raw).get('message', raw)
            except Exception:
                detail = raw
            raise UserError(
                f'Finance Service HTTP {e.code}: {detail}'
            )
        except urllib.error.URLError as e:
            raise UserError(
                f'Cannot reach Finance Service at {full_url}: {str(e.reason)}'
            )

    # ── Sync actions ──────────────────────────────────────────────────────────

    def action_sync_to_finance_service(self):
        """Manual sync button."""
        for move in self:
            move._do_sync()

    def _do_sync(self):
        self.ensure_one()
        _, _, tenant_id, _ = self._fs_get_config()
        payload = self._fs_build_payload()
        try:
            if self.fs_invoice_id:
                result = self._fs_request(
                    'PATCH',
                    f'tenants/{tenant_id}/invoices/{self.fs_invoice_id}',
                    payload,
                )
            else:
                result = self._fs_request(
                    'POST',
                    f'tenants/{tenant_id}/invoices',
                    payload,
                )
            self.write({
                'fs_invoice_id':     result.get('id', self.fs_invoice_id),
                'fs_invoice_number': result.get('invoiceNumber', ''),
                'fs_sync_state':     'synced',
                'fs_sync_error':     False,
                'fs_synced_at':      fields.Datetime.now(),
            })
            _logger.info('Synced Odoo %s → FS invoice %s', self.name, result.get('id'))
        except UserError as e:
            self.write({'fs_sync_state': 'error', 'fs_sync_error': str(e)})
            _logger.error('FS sync failed for %s: %s', self.name, e)
            raise

    def _do_sync_payment_status(self):
        self.ensure_one()
        if not self.fs_invoice_id:
            return
        _, _, tenant_id, _ = self._fs_get_config()
        try:
            self._fs_request(
                'POST',
                f'tenants/{tenant_id}/invoices/{self.fs_invoice_id}/mark-paid',
                {'paidAt': fields.Datetime.now().strftime('%Y-%m-%dT%H:%M:%S.000Z')},
            )
            self.write({'fs_synced_at': fields.Datetime.now()})
        except UserError as e:
            _logger.warning('Could not mark FS invoice PAID for %s: %s', self.name, e)
            self.write({'fs_sync_error': str(e)})

    # ── Hooks into Odoo lifecycle ─────────────────────────────────────────────

    def action_post(self):
        result = super().action_post()
        for move in self.filtered(
            lambda m: m.move_type in ('out_invoice', 'out_refund') and m.state == 'posted'
        ):
            _, _, _, auto_sync = move._fs_get_config()
            if not auto_sync:
                continue
            try:
                move._do_sync()
            except UserError:
                pass  # error stored on record — don't block confirmation
        return result

    def _invoice_paid_hook(self):
        """Odoo 17 calls this after reconciliation when an invoice becomes paid / in_payment."""
        result = super()._invoice_paid_hook()
        for move in self.filtered(
            lambda m: m.move_type in ('out_invoice', 'out_refund') and m.fs_invoice_id
        ):
            move._do_sync_payment_status()
        return result
