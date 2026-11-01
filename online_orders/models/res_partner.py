import re

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Fields of a delivery address whose changes by staff are logged on the customer
LOGGED_ADDRESS_FIELDS = [
    'name', 'phone', 'street', 'street2', 'city', 'state_id', 'country_id',
    'partner_latitude', 'partner_longitude', 'address_label', 'delivery_directions',
]
NUMBER = r'(-?\d{1,3}(?:\.\d+)?)'
# Most precise first: the place pin, then the map centre, then query parameters
COORDINATE_PATTERNS = [
    re.compile(r'!3d' + NUMBER + r'!4d' + NUMBER),
    re.compile(r'@' + NUMBER + r',\s*' + NUMBER),
    re.compile(r'[?&](?:q|query|ll|destination|center)=' + NUMBER + r'(?:,|%2C)\s*\+?' + NUMBER),
    re.compile(r'^\s*' + NUMBER + r'\s*[,;\s]\s*' + NUMBER + r'\s*$'),
]


def parse_coordinates(text):
    """'25.0719120, 55.1527595' or a full Google Maps link -> (lat, lng).

    :raise UserError: if no coordinates can be read
    """
    text = (text or '').strip()
    if re.search(r'(maps\.app\.goo\.gl|goo\.gl/maps)', text):
        raise UserError(_(
            "Short Google Maps links can't be read. Open the link, then copy the full address "
            "from the browser bar, or paste the coordinates (e.g. 25.0719120, 55.1527595)."))
    for pattern in COORDINATE_PATTERNS:
        match = pattern.search(text)
        if match:
            lat, lng = float(match.group(1)), float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    raise UserError(_("No coordinates found. Paste them like 25.0719120, 55.1527595 or a full Google Maps link."))


class ResPartner(models.Model):
    _inherit = 'res.partner'

    partner_coordinates = fields.Char(
        'Coordinates', compute='_compute_partner_coordinates',
        help='Latitude, longitude of the map pin, in the format Careem accepts.')
    coordinates_input = fields.Char(
        'Paste Coordinates or Link', compute='_compute_coordinates_input',
        inverse='_inverse_coordinates_input',
        help='Paste "25.0719120, 55.1527595" or a full Google Maps link to set the pin.')
    google_maps_url = fields.Char('Google Maps', compute='_compute_partner_coordinates')
    added_by_staff = fields.Boolean('Added by Staff', compute='_compute_added_by_staff')

    @api.depends('partner_latitude', 'partner_longitude')
    def _compute_partner_coordinates(self):
        for partner in self:
            if partner.partner_latitude and partner.partner_longitude:
                coordinates = '%.7f, %.7f' % (partner.partner_latitude, partner.partner_longitude)
                partner.partner_coordinates = coordinates
                partner.google_maps_url = 'https://www.google.com/maps?q=%s' % coordinates.replace(' ', '')
            else:
                partner.partner_coordinates = False
                partner.google_maps_url = False

    def _compute_coordinates_input(self):
        self.coordinates_input = False

    def _inverse_coordinates_input(self):
        for partner in self.filtered('coordinates_input'):
            lat, lng = parse_coordinates(partner.coordinates_input)
            partner.write({'partner_latitude': lat, 'partner_longitude': lng})

    @api.depends('create_uid')
    def _compute_added_by_staff(self):
        for partner in self:
            user = partner.sudo().create_uid
            partner.added_by_staff = bool(user) and not user.share and not user._is_superuser()

    # ──────────────────────────────────────────────────────────────────────────
    # Log and email when staff add or edit a delivery address
    # ──────────────────────────────────────────────────────────────────────────

    def _online_is_customer_address(self):
        self.ensure_one()
        return bool(self.parent_id) and self.type == 'delivery'

    def _online_is_staff_change(self):
        """A person of our team in the backend (website and system changes run as sudo)."""
        user = self.env.user
        return not self.env.su and not user.share and not user._is_public()

    def _online_address_snapshot(self):
        self.ensure_one()
        values = {}
        for fname in LOGGED_ADDRESS_FIELDS:
            value = self[fname]
            if isinstance(value, models.BaseModel):
                value = value.display_name or ''
            elif self._fields[fname].type == 'selection':
                value = dict(self._fields[fname]._description_selection(self.env)).get(value, '')
            values[fname] = value or ''
        return values

    def _online_log_address_change(self, before=None):
        """Log on the customer's chatter: who, when (message date) and what changed.
        Then send the "Your address was updated" email to the customer."""
        self.ensure_one()
        after = self._online_address_snapshot()
        if before is None:
            title = _("Delivery address added by %s", self.env.user.name)
            lines = [(self._fields[f].string, '', after[f]) for f in LOGGED_ADDRESS_FIELDS if after[f]]
        else:
            title = _("Delivery address updated by %s", self.env.user.name)
            lines = [(self._fields[f].string, before[f], after[f])
                     for f in LOGGED_ADDRESS_FIELDS if before[f] != after[f]]
            if not lines:
                return
        items = Markup('').join(
            Markup('<li>%s: %s</li>') % (label, (Markup('%s → %s') % (old, new)) if old else new)
            for label, old, new in lines)
        customer = self.parent_id
        customer.message_post(
            body=Markup('<p><strong>%s</strong> (%s)</p><ul>%s</ul>') % (title, self.display_name, items),
            subtype_xmlid='mail.mt_note',
        )
        template = self.env.ref('online_orders.mail_template_address_updated', raise_if_not_found=False)
        if template and customer.email:
            website = self.env['website'].sudo().search([
                ('online_orders_email_from', '!=', False),
                ('company_id', 'in', [False, (customer.company_id or self.env.company).id]),
            ], limit=1)
            template.sudo().with_context(
                online_orders_email_from=website.online_orders_email_from,
            ).send_mail(self.id)

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        if self._online_is_staff_change():
            for partner in partners.filtered(lambda p: p._online_is_customer_address()):
                partner._online_log_address_change()
        return partners

    def write(self, vals):
        if not (self._online_is_staff_change() and set(vals) & set(LOGGED_ADDRESS_FIELDS + ['type', 'parent_id'])):
            return super().write(vals)
        addresses = self.filtered(lambda p: p._online_is_customer_address())
        before = {partner.id: partner._online_address_snapshot() for partner in addresses}
        res = super().write(vals)
        for partner in self.filtered(lambda p: p._online_is_customer_address()):
            partner._online_log_address_change(before.get(partner.id))
        return res

    # ──────────────────────────────────────────────────────────────────────────
    # Sales cannot delete addresses (customer from My Account, or a manager)
    # ──────────────────────────────────────────────────────────────────────────

    def _online_check_can_delete_addresses(self):
        user = self.env.user
        if self.env.su or not user.has_group('online_orders.group_online_orders_sales') \
                or user.has_group('online_orders.group_online_orders_management'):
            return
        if any(partner._online_is_customer_address() for partner in self):
            raise UserError(_("Only managers can delete a customer's delivery address."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_online_sales(self):
        self._online_check_can_delete_addresses()

    def action_archive(self):
        self._online_check_can_delete_addresses()
        return super().action_archive()
