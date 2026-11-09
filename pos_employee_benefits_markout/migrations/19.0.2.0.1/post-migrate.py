def migrate(cr, version):
    # Preserve the three main tabs' existing appearance when adding the
    # configurable icon field. Other categories keep the Gift default.
    for name, icon in (
        ('category_staff', 'fa-users'),
        ('category_cafe', 'fa-coffee'),
        ('category_corporate', 'fa-building-o'),
    ):
        cr.execute("""
            UPDATE pos_markout_category AS category
               SET icon = %s
              FROM ir_model_data AS reference
             WHERE reference.module = 'pos_employee_benefits_markout'
               AND reference.model = 'pos.markout.category'
               AND reference.name = %s
               AND reference.res_id = category.id
               AND (category.icon IS NULL OR category.icon = 'fa-gift')
        """, [icon, name])
