# -*- coding: utf-8 -*-
"""Archived invoice documents and their versions with SHA-256 (Unveränderbarkeit).

Like the Pitstop CRM's einvoice_artifacts: append-only. Version 1 is the issued original
(PDF/A-3 + XML). Every later status copy (BEZAHLT / STORNIERT stamp) is a new version;
an outdated copy is marked "superseded", never changed or deleted."""
import hashlib
import io
import logging

from odoo.tools.pdf import OdooPdfFileReader

_logger = logging.getLogger(__name__)

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FscInvoiceArchive(models.Model):
    _name = 'fsc.invoice.archive'
    _description = 'GoBD archived invoice document'
    _order = 'move_id, version, id'
    _rec_name = 'filename'

    move_id = fields.Many2one('account.move', string='Invoice', required=True, readonly=True,
                              index=True, ondelete='restrict')
    company_id = fields.Many2one(related='move_id.company_id', store=True, index=True)
    kind = fields.Selection([('pdf', 'PDF'), ('xml', 'XML')], required=True, readonly=True)
    standard = fields.Char(readonly=True)
    attachment_id = fields.Many2one('ir.attachment', required=True, readonly=True, ondelete='restrict')
    filename = fields.Char(readonly=True)
    mimetype = fields.Char(readonly=True)
    file_size = fields.Integer(string='Size (bytes)', readonly=True)
    sha256 = fields.Char(string='SHA-256', readonly=True)
    archived_at = fields.Datetime(readonly=True, default=fields.Datetime.now)
    archived_by_id = fields.Many2one('res.users', readonly=True, default=lambda self: self.env.user)
    last_check_at = fields.Datetime(string='Last integrity check', readonly=True)
    last_check_ok = fields.Boolean(string='Integrity OK', readonly=True)
    retention_until = fields.Date(related='move_id.fsc_retention_until')
    version = fields.Integer(readonly=True, default=1, group_operator=False)
    stamp = fields.Selection([
        ('issued', 'Issued original'),
        ('paid', 'Paid (BEZAHLT)'),
        ('cancelled', 'Cancelled (STORNIERT)'),
    ], string='Version type', readonly=True, default='issued', required=True)
    state = fields.Selection([
        ('active', 'Active'),
        ('superseded', 'Superseded'),
    ], readonly=True, default='active', required=True)
    superseded_at = fields.Datetime(readonly=True)
    trigger = fields.Char(string='Reason', readonly=True)
    xml_sha256 = fields.Char(string='Embedded XML SHA-256', readonly=True,
                             help='SHA-256 of the e-invoice XML inside the PDF: the same in every version.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            attachment = self.env['ir.attachment'].sudo().browse(vals['attachment_id'])
            raw = attachment.raw or b''
            vals.setdefault('xml_sha256', self._fsc_embedded_xml_sha(raw) if vals.get('kind') == 'pdf' else False)
            vals.update({
                'filename': attachment.name,
                'mimetype': attachment.mimetype,
                'file_size': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(),
                'last_check_at': fields.Datetime.now(),
                'last_check_ok': True,
            })
        return super().create(vals_list)

    def write(self, vals):
        allowed = {'last_check_at', 'last_check_ok'}
        if vals.get('state') == 'superseded':      # the only lifecycle change: active -> superseded
            allowed |= {'state', 'superseded_at'}
            if self.filtered(lambda a: a.stamp == 'issued'):
                raise UserError(_('GoBD: the issued original is never superseded.'))
        if not set(vals) <= allowed:
            raise UserError(_('GoBD: archived documents cannot be changed.'))
        return super().write(vals)

    @api.model
    def _fsc_embedded_xml_sha(self, raw):
        try:
            reader = OdooPdfFileReader(io.BytesIO(raw), strict=False)
            for name, content in reader.getAttachments():
                if name.lower().endswith('.xml'):
                    return hashlib.sha256(content).hexdigest()
        except Exception:  # noqa: BLE001
            _logger.debug('no embedded XML found', exc_info=True)
        return False

    def unlink(self):
        raise UserError(_('GoBD: archived documents cannot be deleted.'))

    def _fsc_verify(self):
        """Re-hash every document. Returns the records that no longer match."""
        failed = self.browse()
        now = fields.Datetime.now()
        for record in self.sudo():
            ok = hashlib.sha256(record.attachment_id.raw or b'').hexdigest() == record.sha256
            if record.last_check_ok and not ok:
                record.move_id._fsc_log('integrity_failed', reason=record.filename,
                                        new={'expected': record.sha256})
                record.move_id.with_context(fsc_system_write=True).fsc_archive_state = 'failed'
            record.write({'last_check_at': now, 'last_check_ok': ok})
            if not ok:
                failed |= record
        return failed

    def action_download(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.attachment_id.id}?download=true',
            'target': 'self',
        }
