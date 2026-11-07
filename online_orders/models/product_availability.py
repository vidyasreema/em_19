from odoo import _, api, models
from odoo.exceptions import AccessError, UserError

# Ribbon fields: a change can make a product out of stock (Annex 4A).
RIBBON_TEMPLATE_FIELD = 'website_ribbon_id'
RIBBON_VARIANT_FIELD = 'variant_ribbon_id'
AVAILABILITY_GROUP = 'online_orders.group_online_orders_sales'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ── Availability: read from the ribbon ───────────────────────────────

    def _online_is_out_of_stock(self, website=None, variant=None, ribbons=None):
        """Out-of-stock ribbon of the variant first, then of the product (like
        the product feed sent to Meta)."""
        self.ensure_one()
        ribbon = (variant and variant.sudo().variant_ribbon_id) or self.sudo().website_ribbon_id
        if not ribbon:
            return False
        if ribbons is None:
            website = website or self.env['website'].get_current_website()
            ribbons = website._online_out_of_stock_ribbons()
        return ribbon in ribbons

    def _online_is_sold_out(self, website=None):
        """No variant of the product can be sold on the website."""
        self.ensure_one()
        template = self.sudo()
        variants = template.product_variant_ids
        if not template.website_ribbon_id and not any(variants.mapped('variant_ribbon_id')):
            return False
        website = website or self.env['website'].get_current_website()
        ribbons = website._online_out_of_stock_ribbons()
        if not variants:
            return self._online_is_out_of_stock(ribbons=ribbons)
        return all(self._online_is_out_of_stock(variant=variant, ribbons=ribbons) for variant in variants)

    def _is_add_to_cart_possible(self, parent_combination=None):
        """Website only: an out-of-stock product cannot be chosen (no weight,
        no Add to cart) on its page, in the optional products or the wishlist."""
        if self and self._online_is_sold_out():
            return False
        return super()._is_add_to_cart_possible(parent_combination=parent_combination)

    # ── Website carts lose the products that become out of stock ─────────

    def write(self, vals):
        res = super().write(vals)
        if RIBBON_TEMPLATE_FIELD in vals:
            self.sudo().product_variant_ids._online_remove_from_open_carts()
        return res

    # ── Product Availability screen (Online Orders > Product Availability) ──

    @api.model
    def _online_check_availability_access(self):
        if not self.env.user.has_group(AVAILABILITY_GROUP):
            raise AccessError(_("Only Online Orders users can change the product availability."))

    @api.model
    def _online_availability_domain(self):
        return [('is_published', '=', True), ('sale_ok', '=', True)]

    def _online_availability_row(self, ribbons):
        """The switch shows the ribbon of the product (the one on the shop card)."""
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'out_of_stock': self._online_is_out_of_stock(ribbons=ribbons),
        }

    @api.model
    def online_availability_list(self):
        """Published website products: name and availability only."""
        self._online_check_availability_access()
        website = self.env['website'].get_current_website()
        ribbons = website._online_out_of_stock_ribbons()
        templates = self.sudo().search(self._online_availability_domain(), order='name, id')
        return [template._online_availability_row(ribbons) for template in templates]

    @api.model
    def online_set_availability(self, template_id, available):
        """The switch: Out of stock puts the "Out of stock" ribbon on the product,
        Available leaves it with no ribbon (Sale, New!... removed too). The
        variant ribbons are cleared, so the website and the Meta catalog show
        exactly what the switch says."""
        self._online_check_availability_access()
        website = self.env['website'].get_current_website()
        template = self.sudo().browse(int(template_id)).exists()
        if not template or not template.filtered_domain(self._online_availability_domain()):
            raise UserError(_("This product is not published on the website anymore. Reload the list."))

        ribbon = self.env['product.ribbon'] if available else website._online_out_of_stock_ribbon()
        if not available and not ribbon:
            raise UserError(_('The "Out of stock" ribbon is missing. Create it in Website > Configuration > Ribbons.'))
        variants = template.with_context(active_test=False).product_variant_ids
        variants.filtered(RIBBON_VARIANT_FIELD).write({RIBBON_VARIANT_FIELD: False})
        if template.website_ribbon_id != ribbon:
            template.write({RIBBON_TEMPLATE_FIELD: ribbon.id})

        if available:
            message = _("Saved: %s is available", template.name)
            note = _("Product Availability: set to Available.")
        else:
            message = _("Saved: %s is out of stock", template.name)
            note = _("Product Availability: set to Out of stock.")
        template.message_post(body=note, author_id=self.env.user.partner_id.id,
                              subtype_xmlid='mail.mt_note')
        return {**template._online_availability_row(website._online_out_of_stock_ribbons()), 'message': message}


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        res = super().write(vals)
        if RIBBON_VARIANT_FIELD in vals:
            self._online_remove_from_open_carts()
        return res

    def _online_remove_from_open_carts(self):
        """Remove these products from the website carts (orders not confirmed and
        not being paid) where they are now out of stock."""
        if not self:
            return
        lines = self.env['sale.order.line'].sudo().search([
            ('product_id', 'in', self.ids),
            ('order_id.state', '=', 'draft'),
            ('order_id.website_id', '!=', False),
        ])
        for order, order_lines in lines.grouped('order_id').items():
            if order.get_portal_last_transaction().state in ('pending', 'authorized', 'done'):
                continue
            order._online_remove_unavailable_lines(order_lines)
