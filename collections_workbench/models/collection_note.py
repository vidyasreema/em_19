from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

CHANNELS = [
    ('email', 'Email'),
    ('call', 'Phone call'),
    ('visit', 'Visit'),
    ('whatsapp', 'WhatsApp'),
    ('other', 'Other'),
]


class CollectionNote(models.Model):
    """Time-stamped follow-up note on a customer (BR-8).

    Append-only at model level: no write, no unlink, for every user. A
    correction is a new note. Notes live on the customer card, not on the
    snapshot, so they survive archiving (BR-6)."""
    _name = 'collection.note'
    _description = 'Collection Note'
    _order = 'create_date desc, id desc'
    _rec_name = 'category_id'

    partner_id = fields.Many2one(
        'res.partner', string="Customer", required=True, index=True, ondelete='cascade')
    category_id = fields.Many2one(
        'collection.note.category', string="Category", required=True, ondelete='restrict')
    body = fields.Text(string="Note")
    date = fields.Date(
        string="Date", required=True, default=lambda self: fields.Date.context_today(self), readonly=True,
        help="Business day the note was written. Promises are measured from this day.")
    promise_date = fields.Date(string="Promised / planned date")
    amount = fields.Monetary(string="Amount", currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True)
    user_id = fields.Many2one(
        'res.users', string="Author", default=lambda self: self.env.user, required=True, readonly=True)
    is_system = fields.Boolean(string="System note", readonly=True)
    channel = fields.Selection(CHANNELS, string="Channel")
    pipeline_id = fields.Many2one('collection.pipeline', string="Pipeline", ondelete='set null')
    stage_id = fields.Many2one('collection.stage', string="Stage", ondelete='set null')
    snapshot_line_id = fields.Many2one(
        'collection.snapshot.line', string="Snapshot line", index=True, ondelete='set null')
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True)

    # category flags, for the table and the rules engine
    category_color = fields.Integer(related='category_id.color')
    requires_date = fields.Boolean(related='category_id.requires_date')
    requires_amount = fields.Boolean(related='category_id.requires_amount')

    # ------------------------------------------------------------------
    # Validation (VR-5, VR-6)
    # ------------------------------------------------------------------
    @api.constrains('category_id', 'promise_date', 'amount', 'date')
    def _check_required_by_category(self):
        for note in self:
            cat = note.category_id
            if cat.requires_date:
                if not note.promise_date:
                    raise ValidationError(_(
                        '"%s" needs a date: a promise without a date cannot be followed or measured.',
                        cat.name))
                if note.promise_date < note.date:
                    raise ValidationError(_(
                        'The date for "%s" cannot be in the past.', cat.name))
            if cat.requires_amount and (note.amount or 0.0) <= 0:
                raise ValidationError(_(
                    '"%s" needs an amount: the mismatch check and the promise kept '
                    'ratio are computed on it.', cat.name))

    # ------------------------------------------------------------------
    # Append-only (BR-8, VR-4, Appendix C)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('is_system') and vals.get('category_id'):
                cat = self.env['collection.note.category'].browse(vals['category_id'])
                if cat.is_system:
                    raise UserError(_('"%s" is written by the system only.', cat.name))
        notes = super().create(vals_list)
        notes.partner_id._collection_after_notes(notes)
        return notes

    def write(self, vals):
        raise UserError(_("Notes cannot be edited. Add a correction note instead."))

    def unlink(self):
        raise UserError(_("Notes cannot be deleted. Add a correction note instead."))

    # ------------------------------------------------------------------
    # Promise evaluation (FR-19) — same logic as the simulation
    # ------------------------------------------------------------------
    def _promise_state(self, today=None):
        """'pending' | 'kept' | 'broken' | False (not a promise)."""
        self.ensure_one()
        if not self.category_id.is_promise or not self.promise_date:
            return False
        today = today or fields.Date.context_today(self)
        company = self.company_id or self.env.company
        limit = fields.Date.add(self.promise_date, days=company.collection_grace_days)
        if limit > today:
            return 'pending'
        paid = self.partner_id._collection_paid_between(self.date, limit)
        needed = (self.amount or 0.0) * company.collection_keep_ratio / 100.0
        return 'kept' if paid + 0.005 >= needed else 'broken'
