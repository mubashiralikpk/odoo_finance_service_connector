# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError

PROTECTED_WRITE_FIELDS = {'raw', 'datas', 'db_datas', 'store_fname', 'res_model', 'res_id', 'res_field'}


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _fsc_archived(self):
        if not self.ids:
            return self.browse()
        archived = self.env['fsc.invoice.archive'].sudo().search([('attachment_id', 'in', self.ids)])
        return archived.attachment_id

    def write(self, vals):
        if PROTECTED_WRITE_FIELDS.intersection(vals) and self._fsc_archived():
            raise UserError(_('GoBD: this file is an archived invoice document and cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        if self._fsc_archived():
            raise UserError(_('GoBD: this file is an archived invoice document and cannot be deleted.'))
        return super().unlink()
