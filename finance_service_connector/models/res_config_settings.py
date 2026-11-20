# -*- coding: utf-8 -*-
import json
import urllib.error
import urllib.request

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fs_api_url = fields.Char(
        related='company_id.fs_api_url',
        string='Finance Service URL',
        readonly=False,
    )
    fs_api_key = fields.Char(
        related='company_id.fs_api_key',
        string='API Key',
        readonly=False,
    )
    fs_tenant_id = fields.Char(
        related='company_id.fs_tenant_id',
        string='Tenant ID',
        readonly=False,
    )
    fs_auto_sync = fields.Boolean(
        related='company_id.fs_auto_sync',
        string='Auto-sync on Invoice Confirmation',
        readonly=False,
    )

    # ── Test Connection button ────────────────────────────────────────────────
    def action_fs_test_connection(self):
        """Call GET /api/v1/tenants/me with the entered URL + API key and check
        that the key belongs to the entered Tenant ID."""
        self.ensure_one()
        url = (self.fs_api_url or '').strip().rstrip('/')
        api_key = (self.fs_api_key or '').strip()
        tenant_id = (self.fs_tenant_id or '').strip()

        missing = [label for label, value in (
            ('API URL', url), ('Tenant ID', tenant_id), ('API Key', api_key),
        ) if not value]
        if missing:
            return self._fs_notify(
                'warning', 'Finance Service not configured',
                'Fill in: %s' % ', '.join(missing),
            )

        full_url = f'{url}/api/v1/tenants/me'
        req = urllib.request.Request(full_url, method='GET', headers={
            'Accept': 'application/json',
            'x-api-key': api_key,
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                tenant = json.loads(resp.read().decode('utf-8') or '{}')
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return self._fs_notify(
                    'danger', 'API key rejected',
                    'The Finance Service refused this API key (HTTP %s). '
                    'Check the key is correct, not revoked, and the tenant is not disabled.' % e.code,
                )
            if e.code == 404:
                return self._fs_notify(
                    'danger', 'Wrong API URL',
                    f'{full_url} returned 404. The URL should be the backend root, '
                    'e.g. http://host.docker.internal:3000 (without /api/v1).',
                )
            return self._fs_notify('danger', 'Finance Service error', f'HTTP {e.code} from {full_url}')
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, 'reason', e)
            hint = ''
            if 'localhost' in url or '127.0.0.1' in url:
                hint = ' Odoo runs in Docker: use http://host.docker.internal:3000 instead of localhost.'
            return self._fs_notify(
                'danger', 'Cannot reach Finance Service',
                f'{full_url}: {reason}. Is the backend running (npm run start:dev)?{hint}',
            )
        except ValueError:
            return self._fs_notify('danger', 'Unexpected response', f'{full_url} did not return JSON.')

        name = tenant.get('name') or '?'
        if str(tenant.get('id', '')) != tenant_id:
            return self._fs_notify(
                'danger', 'Tenant ID does not match',
                'This API key belongs to tenant "%s" (%s), not to the Tenant ID entered.'
                % (name, tenant.get('id')),
            )
        return self._fs_notify(
            'success', 'Connected',
            'Finance Service OK — tenant "%s" (%s), currency %s. Remember to Save.'
            % (name, tenant.get('slug') or tenant_id, tenant.get('currency') or 'EUR'),
        )

    def _fs_notify(self, kind, title, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': kind,               # success | warning | danger | info
                'sticky': kind != 'success',
            },
        }
