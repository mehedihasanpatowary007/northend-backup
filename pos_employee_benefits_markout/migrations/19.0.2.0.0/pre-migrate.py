def migrate(cr, version):
    # Odoo 19 models.Constraint removes the leading attribute underscore when
    # naming its SQL object: <table>_<attribute_without_leading_underscore>.
    # Employee and product scopes replace the old one-rule-per-category limit.
    cr.execute('''
        ALTER TABLE pos_benefit_rule
        DROP CONSTRAINT IF EXISTS pos_benefit_rule_unique_category_company
    ''')
