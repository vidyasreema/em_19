from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # --- Behaviour pattern thresholds (BRD Appendix G) -------------------
    collection_grace_days = fields.Integer(
        string="Promise grace (days)", default=3,
        help="Days after the promised date before a promise is judged kept or broken.")
    collection_keep_ratio = fields.Integer(
        string="Promise kept ratio (%)", default=50,
        help="A promise counts as kept when at least this share of the promised "
             "amount is paid by the promised date + grace.")
    collection_repeat_broken = fields.Integer(
        string="Repeat after (broken promises)", default=2)
    collection_chronic_broken = fields.Integer(
        string="Chronic after (broken promises)", default=3)
    collection_chronic_days = fields.Integer(
        string="Chronic after (days open)", default=60,
        help="A broken promise left unpaid for this many days makes the customer chronic.")
    collection_unreach_streak = fields.Integer(
        string="Unreachable after (no answer in a row)", default=2)
    collection_pattern_window = fields.Integer(
        string="Evaluation window (days)", default=0,
        help="Only promises from the last N days count. 0 = all history.")

    # --- Partial payment ---------------------------------------------------
    collection_partial_enabled = fields.Boolean(
        string="Partial payment stage", default=True)
    collection_partial_wait = fields.Integer(
        string="Partial payment pause (days)", default=7)

    # --- People, sender, tags ---------------------------------------------
    collection_employee_ids = fields.Many2many(
        'hr.employee', 'collection_company_employee_rel', 'company_id', 'employee_id',
        string="People collections can be assigned to")
    collection_sender_email = fields.Char(
        string="Sender email",
        help="Official accountant address used as sender of collection emails. "
             "Empty = the current user's email.")
    collection_agreement_tag_ids = fields.Many2many(
        'res.partner.category', 'collection_company_agreement_tag_rel', 'company_id', 'tag_id',
        string="Agreement tags")
    collection_court_tag_ids = fields.Many2many(
        'res.partner.category', 'collection_company_court_tag_rel', 'company_id', 'tag_id',
        string="Court case tags")
    collection_blacklist_tag_ids = fields.Many2many(
        'res.partner.category', 'collection_company_blacklist_tag_rel', 'company_id', 'tag_id',
        string="Blacklist tags")
    collection_vip_tag_ids = fields.Many2many(
        'res.partner.category', 'collection_company_vip_tag_rel', 'company_id', 'tag_id',
        string="VIP / High Profile tags",
        help="Customers with one of these tags go to the Approvals queue on stages "
             "that require approval.")

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._collection_init_default_settings()
        return companies

    def _collection_init_default_settings(self):
        Tag = self.env['res.partner.category']

        def tags(*names):
            found = Tag
            for name in names:
                found |= Tag.search([('name', '=ilike', name)], limit=1)
            return found

        agreement = tags('Agreement: Cheque')
        court = self.env.ref('collections_workbench.tag_court_case', raise_if_not_found=False) or Tag
        blacklist = self.env.ref('collections_workbench.tag_blacklist', raise_if_not_found=False) or Tag
        vip = tags('High Profile', 'VIP')
        for company in self:
            vals = {}
            if not company.collection_agreement_tag_ids and agreement:
                vals['collection_agreement_tag_ids'] = [(6, 0, agreement.ids)]
            if not company.collection_court_tag_ids and court:
                vals['collection_court_tag_ids'] = [(6, 0, court.ids)]
            if not company.collection_blacklist_tag_ids and blacklist:
                vals['collection_blacklist_tag_ids'] = [(6, 0, blacklist.ids)]
            if not company.collection_vip_tag_ids and vip:
                vals['collection_vip_tag_ids'] = [(6, 0, vip.ids)]
            if vals:
                company.write(vals)
