# GoBD requirement matrix — German E-Invoice (GoBD, ZUGFeRD, XRechnung) 2.0 (Odoo 17)

Application controls only; this is not a certificate. Legal basis: BMF-Schreiben GoBD
(28.11.2019, changes 11.03.2024 and 14.07.2025), §14, §14a, §14b UStG, §33 UStDV, §147 AO,
EN 16931. Mirrors `docs/gobd/gobd-requirement-matrix.md` of Pitstop-CRM-tenant.

| Requirement | Legal reference | Implementation | Test | Status | Owner |
| --- | --- | --- | --- | --- | --- |
| Completeness (Vollständigkeit) | GoBD; §147 AO; §14b UStG | Original PDF/A-3 and XML archived at issue; credit notes as separate documents; invoices posted before install adopted | Scenario + upgrade test | Pass | application |
| Correctness (Richtigkeit) | GoBD; §14 Abs. 4 UStG; EN 16931 | Issue blocked until §14 content and VAT rules are met; Odoo EN 16931 constraints run at posting; XML valid against CEN schematron | 49 checks; schematron 0 errors | Pass | application |
| Timely recording | GoBD | Issue timestamp and user; invoice date set at posting | Scenario | Pass (booking discipline: organisation) | organisation |
| Order (Ordnung) | GoBD | Sequential numbering per journal; invoice types; GoBD menu with archive and audit log | UI | Pass | application |
| Traceability (Nachvollziehbarkeit) | GoBD; §147 AO | Insert-only audit log, SHA-256 chain per company; refused resets/deletes logged; Odoo audit trail on | Tamper test (edited row detected) | Pass | application |
| Verifiability (Nachprüfbarkeit) | GoBD Z1/Z2/Z3 | Read access for accountants; GoBD export ZIP with CSV + GDPdU index.xml + originals + SHA256SUMS | Export check | Pass | application |
| Immutability (application) | GoBD; §14b UStG | No edit / reset / cancel / delete of issued invoices; archived files and archive records cannot change; Odoo hash lock on sales journals | Scenario | Pass | application |
| Immutability (storage, WORM) | GoBD | SHA-256 in the same database is tamper-evident, not WORM. Use object-locked storage for the filestore | — | Open | devops |
| Availability (Verfügbarkeit) | GoBD; §147 AO | Retention 8 years from end of issue year (+ extra years); legal hold; deletion refused | Scenario | Pass | application |
| Readability (Lesbarkeit) | §14b UStG | PDF/A-3 + XML kept; download from archive | PDF checks | Pass (veraPDF not run) | application |
| Machine evaluation | GoBD Z3 | CSV with GDPdU description + original XML + data dictionary | Export check | Pass | application |
| Data security | GoBD / IT | Odoo access rights, multi-company rules; backups and encryption | — | Open | devops |
| Procedure documentation | GoBD | This file and README; company-specific Verfahrensdokumentation still needed | — | Open | tax adviser |
| VAT treatment | §14 Abs. 4 Nr. 8, §14a UStG; EN 16931 BR-AE/IC/G/Z/O | Explicit VAT category for 0 %; legal reason; buyer VAT for AE/K; destination checks; O refused | Scenario | Pass | application |
| E-invoice format | EN 16931; ZUGFeRD 2.x / Factur-X; XRechnung | Factur-X EN16931 profile embedded in PDF/A-3; XRechnung via Odoo for B2G | Schematron | Pass (XRechnung: not validated with KoSIT) | application |

## UStG mapping (text as amended by Art. 5 G v. 29.6.2026)

| Paragraph | Requirement | In the module |
| --- | --- | --- |
| §14 Abs. 1 | E-Rechnung = structured format per EN 16931 (or agreed, extractable format) | Factur-X / ZUGFeRD EN16931 embedded in every PDF; XRechnung (UBL) for B2G customers |
| §14 Abs. 2 Nr. 1 + §27 Abs. 38 | Domestic B2B must be an E-Rechnung (paper / other formats only for supplies until 31.12.2026, or until 31.12.2027 with ≤ 800 000 € turnover) | Hybrid PDF/A-3 + EN16931 XML for all customer invoices, so no switch is needed at the deadline |
| §14 Abs. 2 S. 2 | Invoice within 6 months after the supply | Not enforced (organisation) |
| §14 Abs. 3 | Authenticity, integrity, readability; reliable audit trail | Archive with SHA-256, insert-only hash-chained audit log, Odoo hash lock, issued invoices locked |
| §14 Abs. 4 Nr. 1 | Full name and address of supplier and recipient | Checked before issue (recipient address optional ≤ 250 € gross, §33 UStDV) |
| §14 Abs. 4 Nr. 2 | Steuernummer or USt-IdNr. | Checked; both printed and written to the XML (BT-31 / BT-32) |
| §14 Abs. 4 Nr. 3, 4 | Issue date, unique sequential number | Odoo invoice date and journal sequence; number locked after issue |
| §14 Abs. 4 Nr. 5 | Quantity and kind of goods / services | Every line needs a description |
| §14 Abs. 4 Nr. 6 | Time of supply | Delivery / service date or period, printed and in the XML (BT-72 / BG-14) |
| §14 Abs. 4 Nr. 7, 8 | Net amount per rate / exemption, rate and tax amount or exemption note | Exactly one VAT tax per line; 0 % needs an explicit category and a reason; statement printed |
| §14 Abs. 4 Nr. 9 | Note on the recipient's 2-year retention (§14b Abs. 1 S. 5) | Not covered (property-related services to private persons) |
| §14 Abs. 4 Nr. 10 | „Gutschrift" only for self-billing | Corrections are titled „Rechnungskorrektur", never „Gutschrift" |
| §14a Abs. 1, 3 | EU reverse charge / intra-EU supply: statement, both VAT IDs, invoice by the 15th of the following month | Statement and both VAT IDs enforced; the 15th-day deadline is not enforced |
| §14a Abs. 5 | §13b: „Steuerschuldnerschaft des Leistungsempfängers", no separate VAT | Statutory phrase printed for AE; AE is 0 % |
| §14a Abs. 6, 7 | Travel agencies, margin scheme, triangular trade | Not supported (taxes stay blocked until configured with a legal note) |
| §14b Abs. 1 | Keep 8 years from the end of the issue year | Retention date = 31.12. of issue year + 8 (+ extra years), deletion refused, legal hold |
| §14b Abs. 2 | Storage in Germany / EU | Organisation / hosting |
| §4a | VAT refund for charitable bodies exporting goods; needs a §14 invoice with VAT shown separately | No invoice change needed: issued invoices meet §14 |

## Validation evidence

| Document | Validator | Result |
| --- | --- | --- |
| Factur-X CII (invoice, credit note, K, G, B2G) | CEN EN 16931 CII XSD + schematron | 0 errors, 0 warnings |
| XRechnung UBL (invoice with/without buyer VAT ID, credit note) | CEN EN 16931 UBL schematron (BR-, BR-CO-, BR-S/AE/IC/G/Z/O, UBL-SR) | 0 errors, 0 warnings |
| XRechnung UBL | KoSIT XRechnung schematron (BR-DE-*) | 0 errors, 0 warnings |
| UBL XSD, PDF/A (veraPDF) | — | Not run |
