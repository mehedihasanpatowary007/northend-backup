from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    # The legacy mapping view exists only on early releases. Resolve it
    # optionally so new/repeated upgrades do not log a missing-XML-ID warning.
    env = api.Environment(cr, SUPERUSER_ID, {})
    legacy = env.ref(
        'pos_employee_benefits_markout.hr_employee_pos_markout_mapping',
        raise_if_not_found=False,
    )
    if legacy and legacy._name == 'ir.ui.view':
        legacy.unlink()
    # Freshly prepared usage must manufacture before its final stock issue.
    # Keep existing-stock damage/return policies and historical transactions.
    cr.execute("""
        UPDATE pos_markout_category AS category
           SET stock_policy = 'prepare'
          FROM ir_model_data AS reference
         WHERE reference.model = 'pos.markout.category'
           AND reference.module = 'pos_employee_benefits_markout'
           AND reference.res_id = category.id
           AND reference.name IN (
               'category_staff_food_drink', 'category_cafe_customer_feedback',
               'category_cafe_training', 'category_corporate_guests',
               'category_corporate_customers', 'category_corporate_vendors',
               'category_corporate_development'
           )
           AND category.stock_policy IN ('unconfigured', 'consume')
    """)
