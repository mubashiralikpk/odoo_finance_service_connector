# German E-Invoice (GoBD, ZUGFeRD, XRechnung)

By [Ähdus Technology](https://ahdustechnology.com/).

Odoo 17 module for **GoBD-compliant German invoicing**. It runs inside Odoo on its own:
there is no connection to an external service. The invoice rules follow the Pitstop CRM
invoicing module (Pitstop-CRM-tenant) and Odoo's built-in e-invoicing.

The module is in [`finance_service_connector/`](finance_service_connector). Branch `17.0` is the
one the Odoo Apps Store reads.

## What it does

| Rule | In Odoo |
| --- | --- |
| **1. Invoice creation** | An invoice can only be confirmed when the content of §14 Abs. 4 UStG and EN 16931 is there: seller address and VAT ID / tax number, member address (not needed up to 250 € gross, §33 UStDV), delivery / service date or period, a description and exactly one VAT tax per line. Missing items are listed on the draft and block **Confirm**. |
| **2. Invoice saving** | At confirmation the PDF/A-3 (with the XML inside) and the XML are archived with SHA-256 hashes. Issued invoices cannot be edited, reset to draft, cancelled or deleted, and their files cannot be replaced; a correction is always a credit note that references the original. Every step is in an insert-only audit log whose entries are chained by SHA-256. Odoo's hash lock and audit trail are switched on. |
| **3. Retention** | 8 years from the end of the issue year (§14b UStG, §147 AO): a 2026 invoice is kept until 31.12.2034. Retention can be extended per invoice and a legal hold can be set, both with a reason. A daily job re-hashes the archive and checks the audit chain. |
| **4. VAT** | 0 % lines need an explicit EN 16931 VAT category (never guessed). E / AE / K / G need a legal reason; reverse charge (AE) and intra-EU (K) need the customer's VAT ID; K needs a customer in another EU country; exports (G) need a customer outside the EU and an export evidence reference; category O is refused. Unambiguous German taxes (SKR03 / SKR04) are mapped automatically. |
| **5. EN 16931** | Factur-X / ZUGFeRD XML with the EN 16931 profile (`urn:cen.eu:en16931:2017`), including buyer reference / Leitweg-ID (BT-10), tax number (BT-32), service period (BG-14), notes, payment terms and the preceding invoice on credit notes (BT-25). XRechnung (UBL) for B2G customers comes from Odoo. |
| **6. PDF** | Every customer invoice PDF is PDF/A-3 with `factur-x.xml` embedded and Factur-X metadata "EN 16931". The PDF shows the recipient address of the invoice, the service date or period, member number, buyer reference, VAT ID / tax number, intro text, payment terms, postscript, VAT statements (e.g. "Steuerschuldnerschaft des Leistungsempfängers") and, on credit notes, the corrected invoice. Works with Odoo's DIN 5008 layout. |

**GoBD export (Z3):** Invoicing → GoBD → GoBD export gives one ZIP per period for the tax
auditor: CSV tables with a GDPdU `index.xml`, the original PDF/XML files, the audit log, a data
dictionary, `manifest.json` and `SHA256SUMS.txt`.

The Finance-style invoice form stays: invoice type (Manual, Membership, Subscription, Events,
Room booking, Driver credits, POS legal, Correction, Other), member address per invoice, member
number, service type / period, buyer reference, document title, introductory text, payment
terms, closing notes and postscript.

## Install

1. Put `finance_service_connector` on your Odoo addons path.
2. Apps → Update Apps List → install **German E-Invoice (GoBD, ZUGFeRD, XRechnung)**. It installs Invoicing,
   `account_edi_ubl_cii`, `account_edi_ubl_cii_tax_extension`, `account_audit_trail` and
   `l10n_din5008` if needed.
3. Settings → Invoicing → **GoBD (Germany)**: enter the Steuernummer if you have no VAT ID,
   check that "Lock issued invoices with hash" is ticked.
4. Your company needs a complete address and a **trusted** bank account
   (Invoicing → Configuration → Bank Accounts → "Send Money"): the e-invoice needs it.
5. For 0 % taxes that were not mapped automatically, set the **Tax Category Code** and an
   exemption reason or legal note on the tax.
6. Optional: Settings → Companies → Document Layout → **DIN 5008**.

For the best PDF/A result install `fonttools` in Odoo's Python (`pip install fonttools`).

### Upgrade from 1.x (Finance Service sync)

```bash
odoo -d <db> -u finance_service_connector --stop-after-init
```

The upgrade removes the sync settings, button and fields, installs the new dependencies and puts
invoices that were already posted under the GoBD rules (locked, retention started, PDF archived
by the daily job).

## Tested

On Odoo 17 Community with the German chart (SKR03): 49 scenario checks (creation rules, VAT
rules, immutability, credit notes, retention / legal hold, payments, export), detection of a
changed archive file and of an edited audit-log row, and the upgrade from 1.1. The generated
Factur-X XML (invoice, credit note, intra-EU K, export G) passes the CEN EN 16931 CII schema and
the official EN 16931 schematron ([ConnectingEurope/eInvoicing-EN16931](https://github.com/ConnectingEurope/eInvoicing-EN16931))
with 0 errors and 0 warnings.

Not covered by these tests: PDF/A validation with veraPDF and XRechnung validation with the KoSIT
validator.

## Limits

This module gives application controls; it is not a GoBD certification. The company still
needs a Verfahrensdokumentation, backups and access rules. Hashes in the same database are
tamper-evident, not WORM storage: for that, put Odoo's filestore on storage with object lock.
See [docs/GOBD.md](docs/GOBD.md).

## License

Odoo Proprietary License v1.0 (OPL-1) — see [LICENSE](LICENSE). Sold on the Odoo Apps Store for 9 EUR (one-time).
