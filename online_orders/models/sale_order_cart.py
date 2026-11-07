from odoo import _, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    """Website carts: a product with the Out of stock ribbon cannot be sold
    online (Annex 4A, 2.3). Backend orders and the POS are not affected."""
    _inherit = 'sale.order'

    def _online_unavailable_lines(self, lines=None):
        self.ensure_one()
        lines = self.order_line if lines is None else lines
        if not self.website_id or not lines:
            return lines.browse()
        ribbons = self.website_id._online_out_of_stock_ribbons()
        return lines.filtered(lambda line: line._online_is_out_of_stock(ribbons))

    def _online_remove_unavailable_lines(self, lines=None):
        """Remove the out-of-stock lines of the cart and tell the customer."""
        self.ensure_one()
        unavailable = self._online_unavailable_lines(lines)
        if not unavailable:
            return unavailable
        names = ', '.join(unavailable.mapped('product_id.name'))
        unavailable.sudo().unlink()
        self.sudo().shop_warning = _("%s is out of stock and was removed from your cart.", names)
        return unavailable

    def _verify_updated_quantity(self, order_line, product_id, new_qty, uom_id, **kwargs):
        product = self.env['product.product'].browse(product_id)
        if new_qty > 0 and self.website_id and product.exists() and product.product_tmpl_id._online_is_out_of_stock(
                self.website_id, product):
            if order_line:
                warning = _("%s is out of stock and was removed from your cart.", product.name)
            else:
                warning = _("%s is out of stock and cannot be added to your cart.", product.name)
            return 0, warning
        return super()._verify_updated_quantity(order_line, product_id, new_qty, uom_id, **kwargs)

    def _verify_cart(self):
        """An old cart that comes back (customer logs in) loses its out-of-stock products."""
        super()._verify_cart()
        self._online_remove_unavailable_lines()

    def _check_cart_is_ready_to_be_paid(self):
        """Safety net before the payment: never charge an out-of-stock product."""
        unavailable = self._online_unavailable_lines()
        if unavailable:
            raise ValidationError(_(
                "%s is out of stock. Please remove it from your cart.",
                ', '.join(unavailable.mapped('product_id.name'))))
        return super()._check_cart_is_ready_to_be_paid()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _online_is_out_of_stock(self, ribbons=None):
        self.ensure_one()
        product = self.product_id
        if not product or self.is_delivery or self.display_type or not self.order_id.website_id:
            return False
        return product.product_tmpl_id._online_is_out_of_stock(self.order_id.website_id, product, ribbons)
