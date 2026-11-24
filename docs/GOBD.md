# GoBD requirement matrix — Finance Service Connector 2.0 (Odoo 17)

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
