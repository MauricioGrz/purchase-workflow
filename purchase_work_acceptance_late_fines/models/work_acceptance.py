# Copyright 2020 Ecosoft Co., Ltd. (http://ecosoft.co.th)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WorkAcceptance(models.Model):
    _inherit = "work.acceptance"

    late_days = fields.Integer(
        readonly=True,
        states={"draft": [("readonly", False)]},
        tracking=True,
        help="Late day(s) from Received Date - Due Date",
    )
    fines_rate = fields.Monetary(
        default=lambda self: self.env.company.wa_fines_rate,
        readonly=True,
        states={"draft": [("readonly", False)]},
        tracking=True,
        help="Default fines per day. Can be overwritten",
    )
    fines_late = fields.Monetary(
        string="Fines Amount",
        readonly=True,
        states={"draft": [("readonly", False)]},
        tracking=True,
        help="Computed amount. Can be overwritten",
    )
    fines_invoice_count = fields.Integer(
        compute="_compute_fines_invoice_count",
    )
    fines_invoice_ids = fields.One2many(
        comodel_name="account.move",
        inverse_name="late_wa_id",
        string="Fines Invoices",
    )
    _sql_constraints = [
        ("late_days", "CHECK (late_days>=0)", "Wrong Late Days, it must be positive!"),
        (
            "fines_rate",
            "CHECK (fines_rate>=0)",
            "Wrong Fines Rate, it must be positive!",
        ),
        (
            "fines_late",
            "CHECK (fines_late>=0)",
            "Wrong Fines Amount, it must be positive!",
        ),
    ]

    @api.depends("fines_invoice_ids")
    def _compute_fines_invoice_count(self):
        for rec in self:
            rec.fines_invoice_count = len(rec.fines_invoice_ids)

    def action_view_invoice(self):
        move_ids = self.env.context.get("created_move_ids", [])
        if not move_ids:
            active_ids = self.ids or self.env.context.get("active_ids", [])
            work_acceptances = self.env["work.acceptance"].browse(active_ids)
            move_ids = work_acceptances.mapped("fines_invoice_ids").ids
        if not move_ids:
            raise UserError(_("No fine invoices"))
        result = {
            "name": _("Fines Invoice/Refund"),
            "type": "ir.actions.act_window",
            "view_mode": "tree,kanban,form",
            "res_model": "account.move",
        }
        if len(move_ids) > 1:
            result["domain"] = [("id", "in", move_ids)]
        else:
            res = self.env.ref("account.view_move_form", False)
            result.update(
                {
                    "views": [(res and res.id or False, "form")],
                    "res_id": move_ids[0],
                }
            )
        return result

    def action_create_fines_invoice(self, move_type="out_invoice"):
        AccountMove = self.env["account.move"]
        active_ids = self.ids or self.env.context.get("active_ids", [])
        work_acceptances = self.browse(active_ids)
        if any(wa.fines_late <= 0.0 for wa in work_acceptances):
            raise UserError(_("No late fines on work acceptance(s)"))
        fines_invoices = AccountMove.search(
            [("late_wa_id", "in", work_acceptances.ids), ("state", "!=", "cancel")]
        )
        if fines_invoices:
            names = ", ".join(fines_invoices.mapped("late_wa_id").mapped("name"))
            raise UserError(_("Invoice already created for %s") % names)
        move_dict = self._prepare_late_wa_moves(move_type)
        moves = AccountMove.create(move_dict)
        result = self.with_context(created_move_ids=moves.ids).action_view_invoice()
        return result

    def _prepare_late_wa_moves(self, move_type):
        return [
            {
                "partner_id": wa.partner_id.id,
                "move_type": move_type,
                "late_wa_id": wa.id,
                "invoice_line_ids": [(0, 0, wa._prepare_late_wa_move_line())],
            }
            for wa in self
        ]

    def _prepare_late_wa_move_line(self, name=False):
        return {
            "name": name or _("Work Acceptance Late Delivery Fines %s") % (self.name),
            "account_id": self.env.company.wa_fines_late_account_id,
            "price_unit": self.fines_late,
        }

    @api.onchange("date_receive", "date_due")
    def _onchange_late_days(self):
        late_days = 0
        if self.date_receive and self.date_due:
            late_days = (self.date_receive - self.date_due).days
        self.late_days = late_days > 0 and late_days or 0

    @api.onchange("late_days", "fines_rate")
    def _onchange_fines_late(self):
        fines_late = self.late_days * self.fines_rate
        self.fines_late = fines_late > 0 and fines_late or 0
