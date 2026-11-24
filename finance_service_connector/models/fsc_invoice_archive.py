# -*- coding: utf-8 -*-
"""Archived original invoice documents with SHA-256 (Unveränderbarkeit)."""
import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FscInvoiceArchive(models.Model):
    _name = 'fsc.invoice.archive'
    _description = 'GoBD archived invoice document'
    _order = 'id'
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            attachment = self.env['ir.attachment'].sudo().browse(vals['attachment_id'])
            raw = attachment.raw or b''
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
        if not set(vals) <= {'last_check_at', 'last_check_ok'}:
            raise UserError(_('GoBD: archived documents cannot be changed.'))
        return super().write(vals)

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
