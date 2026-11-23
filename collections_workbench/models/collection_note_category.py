from odoo import fields, models


class CollectionNoteCategory(models.Model):
    _name = 'collection.note.category'
    _description = 'Collection Note Category'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer(string="Colour", default=0)
    active = fields.Boolean(default=True, help="Archive instead of delete: old notes keep their category.")

    requires_date = fields.Boolean(
        string="Requires a date",
        help="A note in this category cannot be saved without a future date "
             "(promise to pay, meeting, visit). The date becomes a deadline.")
    requires_amount = fields.Boolean(
        string="Requires an amount",
        help="A note in this category cannot be saved without an amount.")
    is_promise = fields.Boolean(
        string="Counts as a promise",
        help="Used for the behaviour pattern: judged kept or broken by the payments "
             "received by the date + grace.")
    is_no_answer = fields.Boolean(
        string='Counts as "no answer"',
        help="Several in a row make the customer Unreachable.")
    closes_deadline = fields.Boolean(
        string="Closes deadlines",
        help="Adding a note in this category closes any open deadline.")
    late_on = fields.Selection(
        [('customer', 'Customer'), ('us', 'Us')], string="Late on", default='customer',
        help="When the deadline passes: Overdue on the customer, or Late on us "
             "(e.g. a field visit we did not do).")
    is_paid_claim = fields.Boolean(
        string="Customer says paid",
        help="Used by the payment mismatch check on Refresh (Paid in full / Partial payment).")
    is_blacklist_recommendation = fields.Boolean(
        string="Recommends blacklist",
        help="Adding this note adds the Blacklist tag automatically (BR-19).")
    is_system = fields.Boolean(
        string="System", readonly=True,
        help="Written by the module only (email sent, stage recorded...). Not selectable by users.")

    _name_uniq = models.Constraint('unique(name)', 'A note category with this name already exists.')
