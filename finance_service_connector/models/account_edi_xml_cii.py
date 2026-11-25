# -*- coding: utf-8 -*-
"""
EN 16931 (Factur-X / ZUGFeRD 2.x, profile EN16931) for GoBD invoices.

Odoo 17 writes the Factur-X EXTENDED guideline ID. Pitstop pins the plain
EN16931 profile (urn:cen.eu:en16931:2017), validated with the official CEN
schematron. On top of Odoo's XML this adds:
  - BT-24  guideline ID urn:cen.eu:en16931:2017
  - BT-10  buyer reference / Leitweg-ID from the invoice
  - BT-22  introductory text and postscript as notes
  - BT-20  payment terms text
  - BT-32  seller tax number (Steuernummer, scheme FC)
  - BG-8   buyer address from the invoice snapshot (same as the PDF)
  - BG-14  service period instead of Odoo's invoice-date..due-date period
  - BG-3   preceding invoice reference on credit notes (BT-25/BT-26)
"""
from lxml import etree

from odoo import models

EN16931_GUIDELINE = 'urn:cen.eu:en16931:2017'
NS = {
    'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
    'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
    'udt': 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100',
    'qdt': 'urn:un:unece:uncefact:data:standard:QualifiedDataType:100',
}
RAM = '{%s}' % NS['ram']
QDT = '{%s}' % NS['qdt']
PERIOD_SERVICE_TYPES = ('delivery_period', 'performance_period')


def _el(tag, text=None, **attrs):
    node = etree.Element(RAM + tag, nsmap={'ram': NS['ram']})
    if text is not None:
        node.text = text
    for key, value in attrs.items():
        node.set(key, value)
    return node


class AccountEdiXmlCII(models.AbstractModel):
    _inherit = 'account.edi.xml.cii'

    def _fsc_applies(self, invoice):
        return invoice.move_type in ('out_invoice', 'out_refund')

    def _get_exchanged_document_vals(self, invoice):
        vals = super()._get_exchanged_document_vals(invoice)
        if self._fsc_applies(invoice):
            notes = list(vals.get('included_note_list') or [])
            for text in (invoice.fs_intro_text, invoice.fs_postscript):
                if text and text.strip():
                    notes.append({'content': text.strip(), 'subject_code': None})
            for text in invoice._fsc_legal_statement_lines():
                notes.append({'content': text, 'subject_code': None})
            vals['included_note_list'] = notes
        return vals

    def _export_invoice_vals(self, invoice):
        vals = super()._export_invoice_vals(invoice)
        if not self._fsc_applies(invoice):
            return vals
        vals['document_context_id'] = EN16931_GUIDELINE
        if invoice.fs_buyer_reference:
            vals['buyer_reference'] = invoice.fs_buyer_reference
        # BG-14 = the service period, not invoice date .. due date
        vals.pop('billing_start', None)
        vals.pop('billing_end', None)
        if invoice.fs_service_type in PERIOD_SERVICE_TYPES and invoice.delivery_date and invoice.fs_service_date_to:
            vals['billing_start'] = invoice.delivery_date
            vals['billing_end'] = invoice.fs_service_date_to
        return vals

    def _export_invoice_constraints(self, invoice, vals):
        constraints = super()._export_invoice_constraints(invoice, vals)
        # BR-CO-26 is met by the VAT ID (BT-31) OR the legal registration ID (BT-30)
        if self._fsc_applies(invoice) and invoice.company_id.company_registry:
            constraints.pop('seller_identifier', None)
        return constraints

    def _export_invoice(self, invoice):
        xml, errors = super()._export_invoice(invoice)
        if not self._fsc_applies(invoice) or not xml:
            return xml, errors
        tree = etree.fromstring(xml)
        self._fsc_patch_tree(invoice, tree)
        return etree.tostring(tree, xml_declaration=True, encoding='UTF-8'), errors

    def _fsc_patch_tree(self, invoice, tree):
        agreement = tree.find('.//ram:ApplicableHeaderTradeAgreement', NS)
        settlement = tree.find('.//ram:ApplicableHeaderTradeSettlement', NS)

        # BT-32 seller tax number
        seller = agreement.find('ram:SellerTradeParty', NS)
        tax_number = invoice.company_id.fsc_tax_number
        if seller is not None and tax_number:
            reg = _el('SpecifiedTaxRegistration')
            reg.append(_el('ID', tax_number, schemeID='FC'))
            seller.append(reg)

        # BT-30 register number: Odoo writes scheme 0002 (French SIRENE); only keep it for France
        if seller is not None and invoice.company_id.country_id.code != 'FR':
            for legal_id in seller.findall('ram:SpecifiedLegalOrganization/ram:ID', NS):
                legal_id.attrib.pop('schemeID', None)

        # BG-8 buyer address = invoice snapshot (what the PDF shows)
        buyer = agreement.find('ram:BuyerTradeParty', NS)
        if buyer is not None:
            address = buyer.find('ram:PostalTradeAddress', NS)
            new_address = _el('PostalTradeAddress')
            country = invoice._fsc_buyer_country()
            for tag, value in (
                ('PostcodeCode', invoice.fs_rcpt_zip),
                ('LineOne', invoice.fs_rcpt_street),
                ('LineTwo', invoice.fs_rcpt_street2),
                ('CityName', invoice.fs_rcpt_city),
                ('CountryID', country.code if country else None),
            ):
                if value:
                    new_address.append(_el(tag, value))
            if address is not None:
                address.addprevious(new_address)
                buyer.remove(address)
            email = buyer.find('ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID', NS)
            if email is not None and invoice.fs_rcpt_email:
                email.text = invoice.fs_rcpt_email

        # CII-SR-312: the ship-to party carries no contact in EN 16931
        for contact in tree.findall('.//ram:ShipToTradeParty/ram:DefinedTradeContact', NS):
            contact.getparent().remove(contact)

        # BT-20 payment terms text
        if invoice.fs_payment_terms_text and settlement is not None:
            terms = settlement.find('ram:SpecifiedTradePaymentTerms', NS)
            if terms is None:
                terms = _el('SpecifiedTradePaymentTerms')
                summary = settlement.find('ram:SpecifiedTradeSettlementHeaderMonetarySummation', NS)
                summary.addprevious(terms)
            description = terms.find('ram:Description', NS)
            if description is None:
                description = _el('Description')
                terms.insert(0, description)
            description.text = invoice.fs_payment_terms_text.strip()

        # BG-3 preceding invoice on credit notes
        original = invoice.reversed_entry_id
        if invoice.move_type == 'out_refund' and original and settlement is not None:
            summary = settlement.find('ram:SpecifiedTradeSettlementHeaderMonetarySummation', NS)
            ref = _el('InvoiceReferencedDocument')
            ref.append(_el('IssuerAssignedID', original.name))
            if original.invoice_date:
                formatted = _el('FormattedIssueDateTime')
                date_node = etree.SubElement(formatted, QDT + 'DateTimeString', nsmap={'qdt': NS['qdt']})
                date_node.set('format', '102')
                date_node.text = original.invoice_date.strftime('%Y%m%d')
                ref.append(formatted)
            summary.addnext(ref)
        return tree


class AccountEdiXmlUBLDE(models.AbstractModel):
    _inherit = 'account.edi.xml.ubl_de'

    def _export_invoice_vals(self, invoice):
        vals = super()._export_invoice_vals(invoice)
        if invoice.move_type in ('out_invoice', 'out_refund') and invoice.fs_buyer_reference:
            vals['vals']['buyer_reference'] = invoice.fs_buyer_reference
        return vals
