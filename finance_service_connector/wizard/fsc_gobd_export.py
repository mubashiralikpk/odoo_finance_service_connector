# -*- coding: utf-8 -*-
"""
GoBD data access Z3 (Datenträgerüberlassung): one ZIP per period with
machine-readable CSV + GDPdU index.xml, the original archived PDF/XML files,
the audit log, a data dictionary, a manifest and SHA256SUMS.txt.
"""
import csv
import hashlib
import io
import json
import zipfile
from xml.sax.saxutils import escape

from odoo import _, fields, models
from odoo.exceptions import UserError


def _num(value, digits=2):
    return ('%.*f' % (digits, value or 0.0)).replace('.', ',')


def _date(value):
    return value.strftime('%d.%m.%Y') if value else ''


TABLES = {
    'rechnungen.csv': {
        'name': 'Rechnungen',
        'description': 'Ausgangsrechnungen und Rechnungskorrekturen',
        'key': 'Beleg_ID',
        'columns': [
            ('Beleg_ID', 'alnum'), ('Rechnungsnummer', 'alnum'), ('Belegart', 'alnum'),
            ('Rechnungsart', 'alnum'), ('Status', 'alnum'), ('Rechnungsdatum', 'date'),
            ('Leistungsdatum', 'date'), ('Leistungszeitraum_bis', 'date'), ('Faellig_am', 'date'),
            ('Kunde', 'alnum'), ('Kunden_USt_IdNr', 'alnum'), ('Mitgliedsnummer', 'alnum'),
            ('Land', 'alnum'), ('Waehrung', 'alnum'), ('Netto', 'num'), ('Steuer', 'num'),
            ('Brutto', 'num'), ('Offen', 'num'), ('Zahlstatus', 'alnum'), ('Korrektur_zu', 'alnum'),
            ('Ausgestellt_am', 'alnum'), ('Aufbewahren_bis', 'date'), ('Legal_Hold', 'alnum'),
            ('Archivstatus', 'alnum'),
        ],
    },
    'rechnungspositionen.csv': {
        'name': 'Rechnungspositionen',
        'description': 'Positionen der Ausgangsrechnungen',
        'key': 'Position_ID',
        'columns': [
            ('Position_ID', 'alnum'), ('Beleg_ID', 'alnum'), ('Rechnungsnummer', 'alnum'),
            ('Artikel', 'alnum'), ('Beschreibung', 'alnum'), ('Menge', 'num4'), ('Einheit', 'alnum'),
            ('Einzelpreis_netto', 'num4'), ('Rabatt_Prozent', 'num'), ('Netto', 'num'),
            ('Steuer', 'alnum'), ('Steuersatz', 'num'), ('USt_Kategorie', 'alnum'), ('Brutto', 'num'),
        ],
    },
    'dokumente.csv': {
        'name': 'Dokumente',
        'description': 'Archivierte Originaldokumente (PDF/A-3, XML) mit SHA-256',
        'key': 'Dokument_ID',
        'columns': [
            ('Dokument_ID', 'alnum'), ('Beleg_ID', 'alnum'), ('Rechnungsnummer', 'alnum'),
            ('Art', 'alnum'), ('Standard', 'alnum'), ('Datei', 'alnum'), ('SHA256', 'alnum'),
            ('Archiviert_am', 'alnum'), ('Integritaet_OK', 'alnum'),
        ],
    },
    'protokoll.csv': {
        'name': 'Protokoll',
        'description': 'Audit-Log (verkettete SHA-256-Hashes)',
        'key': 'Ereignis_ID',
        'columns': [
            ('Ereignis_ID', 'alnum'), ('Beleg_ID', 'alnum'), ('Rechnungsnummer', 'alnum'),
            ('Ereignis', 'alnum'), ('Zeitpunkt', 'alnum'), ('Benutzer', 'alnum'), ('Grund', 'alnum'),
            ('Vorher', 'alnum'), ('Nachher', 'alnum'), ('Vorheriger_Hash', 'alnum'), ('Hash', 'alnum'),
        ],
    },
}

DATA_DICTIONARY = {
    'rechnungen.csv': 'One row per issued customer invoice or credit note in the period (by invoice date).',
    'rechnungspositionen.csv': 'Invoice lines; amounts in document currency, net of discount.',
    'dokumente.csv': 'Original documents as archived at issue; files are in documents/.',
    'protokoll.csv': 'Insert-only audit log; Hash = SHA-256(Vorheriger_Hash + event payload).',
    'Aufbewahren_bis': 'End of issue year + legal retention (8 years, §14b UStG / §147 AO) + extra years.',
    'access': {
        'Z1': 'Read-only access in Odoo for authorised staff.',
        'Z2': 'Evaluation by the company on request of the auditor.',
        'Z3': 'This package (Datenträgerüberlassung).',
    },
    'format': 'CSV, UTF-8, ";" separated, CRLF, decimal comma, dates DD.MM.YYYY; described by index.xml (GDPdU).',
}


class FscGobdExport(models.TransientModel):
    _name = 'fsc.gobd.export'
    _description = 'GoBD export (Z3)'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    date_from = fields.Date(required=True, default=lambda self: fields.Date.today().replace(month=1, day=1))
    date_to = fields.Date(required=True, default=fields.Date.today)
    include_documents = fields.Boolean(string='Include original PDF/XML', default=True)
    file = fields.Binary(readonly=True, attachment=False)
    filename = fields.Char(readonly=True)

    def _moves(self):
        return self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('fsc_issued_at', '!=', False),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
        ], order='invoice_date, name')

    def action_export(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('The start date is after the end date.'))
        moves = self._moves()
        files = {}

        def write_csv(name, rows):
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator='\r\n')
            writer.writerow([c for c, _t in TABLES[name]['columns']])
            writer.writerows(rows)
            files[name] = buffer.getvalue().encode('utf-8')

        status = dict(self.env['account.move']._fields['payment_state']._description_selection(self.env))
        write_csv('rechnungen.csv', [[
            m.id, m.name, 'Rechnung' if m.move_type == 'out_invoice' else 'Rechnungskorrektur',
            m.fs_invoice_type or '', m.state, _date(m.invoice_date), _date(m.delivery_date),
            _date(m.fs_service_date_to), _date(m.invoice_date_due), m.partner_id.display_name,
            m.partner_id.commercial_partner_id.vat or '', m.fs_rcpt_member_number or '',
            (m.fs_rcpt_country_id or m.partner_id.country_id).code or '', m.currency_id.name,
            _num(m.amount_untaxed), _num(m.amount_tax), _num(m.amount_total), _num(m.amount_residual),
            status.get(m.payment_state, m.payment_state), m.reversed_entry_id.name or '',
            fields.Datetime.to_string(m.fsc_issued_at), _date(m.fsc_retention_until),
            'ja' if m.fsc_legal_hold else 'nein', m.fsc_archive_state,
        ] for m in moves])

        line_rows = []
        for m in moves:
            for line in m.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                tax = line.tax_ids[:1]
                line_rows.append([
                    line.id, m.id, m.name, line.product_id.display_name or '', line.name or '',
                    _num(line.quantity, 4), line.product_uom_id.name or '', _num(line.price_unit, 4),
                    _num(line.discount), _num(line.price_subtotal), tax.name or '', _num(tax.amount),
                    m._fsc_tax_category(tax) or '' if tax else '', _num(line.price_total),
                ])
        write_csv('rechnungspositionen.csv', line_rows)

        archives = moves.fsc_archive_ids
        write_csv('dokumente.csv', [[
            a.id, a.move_id.id, a.move_id.name, a.kind, a.standard or '',
            f'documents/{a.move_id.id}_v{a.version}_{a.filename}', a.sha256,
            fields.Datetime.to_string(a.archived_at), 'ja' if a.last_check_ok else 'nein',
        ] for a in archives])

        events = self.env['fsc.audit.event'].sudo().search([
            ('company_id', '=', self.company_id.id), ('move_id', 'in', moves.ids)], order='id')
        write_csv('protokoll.csv', [[
            e.id, e.move_id.id or '', e.move_id.name or '', e.event_type,
            fields.Datetime.to_string(e.event_at), e.user_id.name or '', e.reason or '',
            e.old_value or '', e.new_value or '', e.prev_hash or '', e.hash or '',
        ] for e in events])

        if self.include_documents:
            for archive in archives:
                files[f'documents/{archive.move_id.id}_v{archive.version}_{archive.filename}'] = archive.attachment_id.raw or b''

        files['index.xml'] = self._gdpdu_index().encode('utf-8')
        files['data-dictionary.json'] = json.dumps(DATA_DICTIONARY, indent=2, ensure_ascii=False).encode('utf-8')
        broken = self.env['fsc.audit.event'].sudo()._verify_chain(self.company_id)
        integrity_failed = archives.filtered(lambda a: not a.last_check_ok)
        manifest = {
            'company': self.company_id.name,
            'company_vat': self.company_id.vat,
            'company_tax_number': self.company_id.fsc_tax_number,
            'period': [str(self.date_from), str(self.date_to)],
            'generated_at': fields.Datetime.to_string(fields.Datetime.now()),
            'generated_by': self.env.user.name,
            'invoices': len(moves),
            'documents': len(archives) if self.include_documents else 0,
            'audit_chain_ok': not broken,
            'documents_integrity_ok': not integrity_failed,
            'sha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())},
        }
        files['manifest.json'] = json.dumps(manifest, indent=2, ensure_ascii=False).encode('utf-8')
        sums = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
        files['SHA256SUMS.txt'] = ''.join(f'{h}  {n}\n' for n, h in sorted(sums.items())).encode()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as archive_zip:
            for name, raw in sorted(files.items()):
                archive_zip.writestr(name, raw)
        filename = 'GoBD_%s_%s_%s.zip' % (
            (self.company_id.name or 'company').replace(' ', '_'), self.date_from, self.date_to)
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'raw': zip_buffer.getvalue(),
            'mimetype': 'application/zip',
            'res_model': self._name,
            'res_id': self.id,
        })
        self.env['fsc.audit.event'].sudo().create({
            'company_id': self.company_id.id,
            'event_type': 'exported',
            'new_value': json.dumps({
                'period': manifest['period'], 'invoices': len(moves), 'file': filename,
                'sha256': hashlib.sha256(zip_buffer.getvalue()).hexdigest(),
            }, sort_keys=True),
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _gdpdu_index(self):
        """GDPdU 'Beschreibungsstandard' index.xml describing the CSV tables."""
        def column(name, kind):
            if kind == 'num':
                return f'<VariableColumn><Name>{name}</Name><Numeric><Accuracy>2</Accuracy></Numeric></VariableColumn>'
            if kind == 'num4':
                return f'<VariableColumn><Name>{name}</Name><Numeric><Accuracy>4</Accuracy></Numeric></VariableColumn>'
            if kind == 'date':
                return f'<VariableColumn><Name>{name}</Name><Date><Format>DD.MM.YYYY</Format></Date></VariableColumn>'
            return f'<VariableColumn><Name>{name}</Name><AlphaNumeric/></VariableColumn>'

        tables = []
        for url, table in TABLES.items():
            key, *rest = table['columns']
            tables.append(
                '<Table>'
                f'<URL>{url}</URL><Name>{escape(table["name"])}</Name>'
                f'<Description>{escape(table["description"])}</Description>'
                f'<Validity><Range><From>{_date(self.date_from)}</From><To>{_date(self.date_to)}</To></Range></Validity>'
                '<UTF8/><DecimalSymbol>,</DecimalSymbol><DigitGroupingSymbol>.</DigitGroupingSymbol>'
                '<VariableLength><ColumnDelimiter>;</ColumnDelimiter>'
                '<RecordDelimiter>&#13;&#10;</RecordDelimiter><TextEncapsulator>"</TextEncapsulator>'
                f'<VariablePrimaryKey><Name>{key[0]}</Name><AlphaNumeric/></VariablePrimaryKey>'
                + ''.join(column(n, k) for n, k in rest)
                + '</VariableLength></Table>'
            )
        company = self.company_id
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE DataSet SYSTEM "gdpdu-01-09-2004.dtd">\n'
            '<DataSet><Version>1.0</Version>'
            f'<DataSupplier><Name>{escape(company.name or "")}</Name>'
            f'<Location>{escape(", ".join(filter(None, [company.street, company.zip, company.city])))}</Location>'
            '<Comment>German E-Invoice for Odoo (Ähdus Technology) - GoBD Z3</Comment></DataSupplier>'
            f'<Media><Name>GoBD {_date(self.date_from)} - {_date(self.date_to)}</Name>{"".join(tables)}</Media>'
            '</DataSet>\n'
        )
