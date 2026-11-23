from odoo import _, api, fields, models
from odoo.exceptions import UserError

PIPELINE_TYPES = [
    ('collection', 'Collection Follow-up'),
    ('agreement', 'Payment Agreements'),
    ('blacklist', 'Blacklist'),
    ('legal', 'Legal Cases'),
    ('custom', 'Added'),
]


class CollectionPipeline(models.Model):
    """A follow-up Kanban board (BR-17, BR-18). A customer is in one pipeline
    at a time; being outside Collection Follow-up stops collection stage
    emails (VR-9)."""
    _name = 'collection.pipeline'
    _description = 'Collection Pipeline'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    pipeline_type = fields.Selection(PIPELINE_TYPES, string="Type", required=True, default='custom')
    description = fields.Char(string="Who appears in it")
    tag_id = fields.Many2one(
        'res.partner.category', string="Tag added on entry",
        help="Classification tag added automatically when a customer enters this pipeline (BR-19).")
    stage_ids = fields.One2many('collection.stage', 'pipeline_id', string="Stages")
    partner_count = fields.Integer(compute='_compute_partner_count', string="Customers")

    def _compute_partner_count(self):
        data = self.env['res.partner']._read_group(
            [('collection_pipeline_id', 'in', self.ids)], ['collection_pipeline_id'], ['__count'])
        counts = {pipe.id: count for pipe, count in data}
        for pipe in self:
            pipe.partner_count = counts.get(pipe.id, 0)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_added(self):
        for pipe in self:
            if pipe.pipeline_type != 'custom':
                raise UserError(_('"%s" is a standard pipeline and cannot be deleted.', pipe.name))
            if pipe.partner_count:
                raise UserError(_('"%s" still has customers. Move them out first.', pipe.name))

    @api.model
    def board_tabs(self):
        """Tabs of the follow-up board, each with its count (FR-21)."""
        tabs = [{
            'key': 'approvals', 'name': _("Approvals"),
            'count': self.env['collection.approval'].search_count([('state', '=', 'pending')]),
            'action': 'collections_workbench.action_collection_approval',
        }]
        for pipe in self.search([]):
            domain = pipe._board_domain()
            tabs.append({
                'key': pipe.id, 'name': pipe.name,
                'count': self.env['res.partner'].search_count(domain),
                'pipeline_id': pipe.id,
            })
        return tabs

    def _board_domain(self):
        self.ensure_one()
        domain = [('collection_pipeline_id', '=', self.id)]
        if self.pipeline_type == 'collection':
            # customers of the active snapshot not followed up yet (BR-12)
            domain = ['|'] + domain + ['&', ('collection_pipeline_id', '=', False),
                                       ('collection_snapshot_line_ids.snapshot_id.state', '=', 'active')]
        return domain

    def action_open_board(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'res.partner',
            'view_mode': 'kanban,list,form',
            'views': [(self.env.ref('collections_workbench.res_partner_view_kanban_collection').id, 'kanban'),
                      (False, 'list'), (False, 'form')],
            'search_view_id': [self.env.ref('collections_workbench.res_partner_view_search_collection').id],
            'domain': self._board_domain(),
            'context': {'default_collection_pipeline_id': self.id,
                        'search_default_collection_mine': 1 if self.pipeline_type == 'collection' else 0},
        }

    @api.model
    def _get_collection(self):
        return self.search([('pipeline_type', '=', 'collection')], limit=1)


class CollectionStage(models.Model):
    _name = 'collection.stage'
    _description = 'Collection Stage'
    _order = 'pipeline_id, sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    pipeline_id = fields.Many2one('collection.pipeline', required=True, ondelete='cascade', index=True)
    pipeline_type = fields.Selection(related='pipeline_id.pipeline_type', store=True)
    wait_days = fields.Integer(
        string="Days", default=7,
        help="Days in this stage without payment before the next stage is suggested.")
    has_email = fields.Boolean(string="Sends an email")
    template_id = fields.Many2one(
        'mail.template', string="Email template", domain=[('model', '=', 'res.partner')],
        ondelete='set null')
    requires_approval = fields.Boolean(
        string="VIP approval",
        help="For VIP / High Profile customers the move goes to the Approvals queue first (BR-16).")
    sets_credit_limit = fields.Boolean(
        string="Sets credit limit",
        help="Credit sales hold: credit limit = current balance on the customer card (BR-14).")
    suggests_blacklist = fields.Boolean(
        string="Suggests blacklist",
        help="When this stage's days expire with no payment, \"Move to blacklist\" is suggested (VR-13).")
    is_partial = fields.Boolean(
        string="Partial payment stage",
        help="A partial payment pauses escalation here and suggests a remaining balance request (BR-25).")
    fold = fields.Boolean(string="Folded in Kanban")
    partner_count = fields.Integer(compute='_compute_partner_count', string="Customers")

    def _compute_partner_count(self):
        data = self.env['res.partner']._read_group(
            [('collection_stage_id', 'in', self.ids)], ['collection_stage_id'], ['__count'])
        counts = {stage.id: count for stage, count in data}
        for stage in self:
            stage.partner_count = counts.get(stage.id, 0)

    @api.ondelete(at_uninstall=False)
    def _unlink_if_empty(self):
        for stage in self:
            if stage.partner_count:
                raise UserError(_('Stage "%s" still has customers. Move them out first.', stage.name))

    @api.model
    def _collection_link_default_templates(self):
        """Give the default stages their default email once (empty only)."""
        mapping = {
            'stage_claim': 'mail_template_stage_claim',
            'stage_reminder_1': 'mail_template_stage_reminder_1',
            'stage_reminder_2': 'mail_template_stage_reminder_2',
            'stage_reminder_3': 'mail_template_stage_reminder_3',
            'stage_credit_hold': 'mail_template_stage_credit_hold',
            'stage_final_notice': 'mail_template_stage_final_notice',
            'stage_management': 'mail_template_stage_management',
        }
        for stage_xmlid, template_xmlid in mapping.items():
            stage = self.env.ref('collections_workbench.' + stage_xmlid, raise_if_not_found=False)
            template = self.env.ref('collections_workbench.' + template_xmlid, raise_if_not_found=False)
            if stage and template and not stage.template_id:
                stage.write({'template_id': template.id, 'has_email': True})
