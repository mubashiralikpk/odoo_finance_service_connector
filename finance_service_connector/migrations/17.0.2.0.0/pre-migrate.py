# -*- coding: utf-8 -*-
"""Remove the 1.x Finance Service sync views before the new views are validated
(they reference the sync fields that 2.0 no longer has)."""

OLD_VIEWS = (
    'view_move_form_inherit_finance_service',
    'view_out_invoice_tree_inherit_finance_service',
    'res_config_settings_view_form_finance_service',
)


def migrate(cr, version):
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'finance_service_connector' AND model = 'ir.ui.view' AND name IN %s
    """, [OLD_VIEWS])
    view_ids = tuple(r[0] for r in cr.fetchall())
    if not view_ids:
        return
    # inheriting views first, then the views themselves
    cr.execute('DELETE FROM ir_ui_view WHERE inherit_id IN %s', [view_ids])
    cr.execute('DELETE FROM ir_ui_view WHERE id IN %s', [view_ids])
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'finance_service_connector' AND model = 'ir.ui.view' AND name IN %s
    """, [OLD_VIEWS])
