# -*- coding: utf-8 -*-
"""Insert-only, hash-chained GoBD audit log (Nachvollziehbarkeit)."""
import hashlib
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

EVENT_TYPES = [
    ('issued', 'Issued'),
    ('archived', 'Documents archived'),
    ('archive_failed', 'Archiving failed'),
    ('correction', 'Corrected by credit note'),
    ('payment_linked', 'Payment linked'),
    ('legal_hold_set', 'Legal hold set'),
    ('legal_hold_released', 'Legal hold released'),
    ('retention_changed', 'Retention changed'),
    ('reset_blocked', 'Reset to draft refused'),
    ('hard_delete_blocked', 'Delete refused'),
    ('integrity_checked', 'Integrity checked'),
    ('integrity_failed', 'Integrity FAILED'),
    ('exported', 'GoBD export'),
]
GENESIS_HASH = '0' * 64


class FscAuditEvent(models.Model):
    _name = 'fsc.audit.event'
    _description = 'GoBD invoice audit event'
    _order = 'id desc'
    _rec_name = 'event_type'

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True,
                                 default=lambda self: self.env.company)
    move_id = fields.Many2one('account.move', string='Invoice', readonly=True, index=True,
                              ondelete='restrict')
    event_type = fields.Selection(EVENT_TYPES, required=True, readonly=True)
    event_at = fields.Datetime(string='At', required=True, readonly=True, default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='User', readonly=True, default=lambda self: self.env.user)
    reason = fields.Text(readonly=True)
    old_value = fields.Text(string='Before', readonly=True)
    new_value = fields.Text(string='After', readonly=True)
    prev_hash = fields.Char(readonly=True)
    hash = fields.Char(string='SHA-256', readonly=True)

    def _payload(self):
        self.ensure_one()
        return json.dumps({
            'company_id': self.company_id.id,
            'move_id': self.move_id.id or None,
            'event_type': self.event_type,
            'event_at': fields.Datetime.to_string(self.event_at),
            'user_id': self.user_id.id or None,
            'reason': self.reason or None,
            'old_value': self.old_value or None,
            'new_value': self.new_value or None,
        }, sort_keys=True, ensure_ascii=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        for vals in vals_list:
            company_id = vals.get('company_id') or self.env.company.id
            # Serialise writers per company so the chain never forks.
            self.env.cr.execute('SELECT pg_advisory_xact_lock(%s, %s)', (88016931, company_id))
            last = self.sudo().search([('company_id', '=', company_id)], order='id desc', limit=1)
            record = super().create([{**vals, 'company_id': company_id,
                                      'prev_hash': last.hash or GENESIS_HASH}])
            record.with_context(fsc_audit_seal=True).write({
                'hash': hashlib.sha256((record.prev_hash + record._payload()).encode()).hexdigest(),
            })
            records |= record
        return records

    def write(self, vals):
        if self.env.context.get('fsc_audit_seal') and set(vals) == {'hash'} and not any(self.mapped('hash')):
            return super().write(vals)
        raise UserError(_('GoBD: audit log entries cannot be changed.'))

    def unlink(self):
        raise UserError(_('GoBD: audit log entries cannot be deleted.'))

    @api.model
    def _verify_chain(self, company):
        """Return the first event whose hash does not match, or an empty recordset."""
        prev = GENESIS_HASH
        for event in self.sudo().search([('company_id', '=', company.id)], order='id asc'):
            expected = hashlib.sha256((prev + event._payload()).encode()).hexdigest()
            if event.prev_hash != prev or event.hash != expected:
                return event
            prev = event.hash
        return self.browse()

    @api.model
    def _log_outside_transaction(self, moves, event_type, reason=None):
        """Record a refused action. The current transaction will be rolled back
        by the error that follows, so the event is written on its own cursor."""
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, self.env.uid, dict(self.env.context))
                cr.execute('SELECT pg_try_advisory_xact_lock(%s, %s)', (88016931, moves[:1].company_id.id))
                if not cr.fetchone()[0]:
                    _logger.warning('GoBD: %s on %s not logged (audit log busy)', event_type, moves.mapped('name'))
                    return
                for move in moves:
                    env['fsc.audit.event'].sudo().create({
                        'company_id': move.company_id.id,
                        'move_id': move.id,
                        'event_type': event_type,
                        'reason': reason,
                    })
        except Exception as e:  # noqa: BLE001 - never hide the original error
            _logger.warning('GoBD: could not log %s: %s', event_type, e)
