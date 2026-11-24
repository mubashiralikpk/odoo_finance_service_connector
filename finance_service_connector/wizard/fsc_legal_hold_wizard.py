# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.account_move import RETENTION_CLASSES, RETENTION_YEARS


class FscLegalHoldWizard(models.TransientModel):
    _name = 'fsc.legal.hold.wizard'
    _description = 'GoBD legal hold / retention'

    move_id = fields.Many2one('account.move', required=True, readonly=True)
    action = fields.Selection([
        ('set', 'Set legal hold'),
        ('release', 'Release legal hold'),
        ('retention', 'Change retention'),
    ], required=True, default='set')
    reason = fields.Text(required=True)
    hold_until = fields.Date(string='Hold until (optional)')
    retention_class = fields.Selection(RETENTION_CLASSES)
    extra_years = fields.Integer(string='Extra retention years')
    current_hold = fields.Boolean(related='move_id.fsc_legal_hold')
    current_retention_until = fields.Date(related='move_id.fsc_retention_until')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move = self.env['account.move'].browse(res.get('move_id') or self.env.context.get('default_move_id'))
        if move:
            res.setdefault('retention_class', move.fsc_retention_class or 'ustg_14b')
            res.setdefault('extra_years', move.fsc_retention_extra_years)
            if move.fsc_legal_hold:
                res['action'] = 'release'
        return res

    def action_apply(self):
        self.ensure_one()
        move = self.move_id
        if not move.fsc_issued_at:
            raise UserError(_('Only issued invoices have a retention period.'))
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_('A reason is required.'))
        old = {
            'legal_hold': move.fsc_legal_hold,
            'legal_hold_until': str(move.fsc_legal_hold_until or ''),
            'retention_class': move.fsc_retention_class,
            'extra_years': move.fsc_retention_extra_years,
            'retention_until': str(move.fsc_retention_until),
        }
        system = move.with_context(fsc_system_write=True).sudo()
        if self.action == 'set':
            system.write({
                'fsc_legal_hold': True,
                'fsc_legal_hold_reason': reason,
                'fsc_legal_hold_until': self.hold_until,
            })
            event = 'legal_hold_set'
        elif self.action == 'release':
            if not move.fsc_legal_hold:
                raise UserError(_('This invoice has no legal hold.'))
            system.write({'fsc_legal_hold': False, 'fsc_legal_hold_until': False})
            event = 'legal_hold_released'
        else:
            if self.extra_years < 0:
                raise UserError(_('Extra years cannot be negative.'))
            new_class = self.retention_class or move.fsc_retention_class
            def years(retention_class, extra):
                return RETENTION_YEARS.get(retention_class or 'ustg_14b', 8) + (extra or 0)
            if years(new_class, self.extra_years) < years(move.fsc_retention_class, move.fsc_retention_extra_years):
                raise UserError(_('The retention period can only be extended, never shortened.'))
            system.write({
                'fsc_retention_class': new_class,
                'fsc_retention_extra_years': self.extra_years,
            })
            event = 'retention_changed'
        move._fsc_log(event, reason=reason, old=old, new={
            'legal_hold': move.fsc_legal_hold,
            'legal_hold_until': str(move.fsc_legal_hold_until or ''),
            'retention_class': move.fsc_retention_class,
            'extra_years': move.fsc_retention_extra_years,
            'retention_until': str(move.fsc_retention_until),
        })
        return {'type': 'ir.actions.act_window_close'}
