# Odoo Finance Service Connector

Odoo 17 module that syncs customer invoices to an external Finance-as-a-Service API.

The module lives in [`finance_service_connector/`](finance_service_connector). Branch `17.0` is the
one the Odoo Apps Store reads.

## Features

- Pushes customer invoices and credit notes to the Finance Service on **Confirm**, or with the
  **Sync to Finance Service** button. Re-syncing updates the same remote invoice.
- Marks the remote invoice **paid** when the invoice is paid in Odoo.
- Finance-style invoice form: invoice type, member address snapshot, member number,
  delivery / service type and date, buyer reference / Leitweg-ID, document title,
  introductory text, payment terms, closing notes, postscript.
- **Finance Service** tab on each invoice (remote ID, number, last sync, error) and a sync column in the list.
- Per-company settings with a **Test Connection** button.

## Install

1. Copy `finance_service_connector` into your Odoo addons path (or mount this repo as `/mnt/extra-addons`).
2. Apps → Update Apps List → install **Finance Service Connector** (requires Invoicing).
3. Settings → Invoicing → **Finance Service**: API URL, Tenant ID, API Key → **Test Connection** → Save.

With Odoo in Docker and the Finance Service on the host, use `http://host.docker.internal:3000` as the API URL.

Upgrade after pulling changes:

```bash
odoo -d <db> -u finance_service_connector --stop-after-init
```

## Finance Service endpoints used

| Purpose | Method | Path |
| --- | --- | --- |
| Test connection | GET | `/api/v1/tenants/me` |
| Create invoice | POST | `/api/v1/tenants/{tenantId}/invoices` |
| Update invoice | PATCH | `/api/v1/tenants/{tenantId}/invoices/{id}` |
| Mark paid | POST | `/api/v1/tenants/{tenantId}/invoices/{id}/mark-paid` |

All requests send the tenant API key in the `x-api-key` header.

## License

LGPL-3.0 — see [LICENSE](LICENSE).
