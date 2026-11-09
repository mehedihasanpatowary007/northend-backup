from odoo import api, fields, models
from odoo.fields import Domain


class PosConfig(models.Model):
    _inherit = "pos.config"

    dashboard_employee_company_ids = fields.Many2many(
        "res.company",
        compute="_compute_dashboard_employee_company_ids",
        string="Companies available for POS employees",
    )
    dashboard_monthly_target = fields.Float(
        string="Monthly sales target",
        digits=(16, 2),
        help="Monthly net sales target used by the POS Performance Dashboard.",
    )

    @api.depends_context("uid")
    def _compute_dashboard_employee_company_ids(self):
        company_ids = self.env.user.company_ids
        for config in self:
            config.dashboard_employee_company_ids = company_ids

    def write(self, vals):
        """Disable pos_hr's automatic employee creation for POS config saves."""
        return super(PosConfig, self.with_context(skip_pos_employee_auto_create=True)).write(vals)

    def _employee_domain(self, user_id):
        """Allow active employees from every company the POS user can access.

        Odoo's default POS-HR domain restricts employees to the POS company. The
        employee record still keeps its required HR company; this only removes
        the POS login restriction and preserves the configured access levels.
        """
        allowed_company_ids = self.env.context.get("pos_allowed_company_ids") or self.env.user.company_ids.ids
        domain = Domain.AND([[("active", "=", True), ("company_id", "in", allowed_company_ids)]])
        basic_employee_ids = self.basic_employee_ids.ids
        if basic_employee_ids:
            domain = Domain.AND([
                domain,
                ["|", ("user_id", "=", user_id), ("id", "in", basic_employee_ids + self.advanced_employee_ids.ids + self.minimal_employee_ids.ids)],
            ])
        return domain


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    dashboard_monthly_target = fields.Float(
        string="Monthly sales target",
        digits=(16, 2),
        help="Monthly net sales target used for this sales officer in the POS Performance Dashboard.",
    )

    @api.model
    def _load_pos_data_search_read(self, data, config):
        """Load allowed-company employees even when the UI has one company selected."""
        allowed_company_ids = self.env.user.company_ids.ids or [self.env.company.id]
        employee_model = self.sudo().with_context(
            allowed_company_ids=allowed_company_ids,
            pos_allowed_company_ids=allowed_company_ids,
        )
        pos_config = config.with_context(
            allowed_company_ids=allowed_company_ids,
            pos_allowed_company_ids=allowed_company_ids,
        )
        return super(HrEmployee, employee_model)._load_pos_data_search_read(data, pos_config)


class ResUsers(models.Model):
    _inherit = "res.users"

    def action_create_employee(self):
        if self.env.context.get("skip_pos_employee_auto_create"):
            return False
        return super().action_create_employee()
