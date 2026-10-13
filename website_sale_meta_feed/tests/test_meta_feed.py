from lxml import etree

from odoo import fields
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.website_sale.tests.common import MockRequest
from odoo.addons.website_sale.tests.common_gmc import WebsiteSaleGMCCommon

G = {'g': 'http://base.google.com/ns/1.0'}


@tagged('post_install', '-at_install')
class TestMetaFeed(WebsiteSaleGMCCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ribbon_out = cls.env['product.ribbon'].create({'name': "Out of stock"})
        cls.ribbon_sale = cls.env['product.ribbon'].create({'name': "Sale"})
        cls.gmc_feed.out_of_stock_ribbon_ids = cls.ribbon_out

        cls.brand_attribute = cls.env['product.attribute'].create({
            'name': "Brand",
            'value_ids': [Command.create({'name': "Global Meat"})],
        })
        cls.steak_tmpl = cls.env['product.template'].create({
            'name': "Wagyu T-Bone",
            'list_price': 129.99,
            'is_published': True,
            'description_ecommerce': "<p>Rich <b>marbling</b>,</p><p>best grilled.</p>",
            'attribute_line_ids': [Command.create({
                'attribute_id': cls.brand_attribute.id,
                'value_ids': [Command.set(cls.brand_attribute.value_ids.ids)],
            })],
        })
        cls.steak = cls.steak_tmpl.product_variant_id

    def render_feed(self):
        feed = self.gmc_feed.with_context(lang=self.gmc_feed.lang_id.code)
        with MockRequest(feed.env, website=feed.website_id):
            return etree.XML(feed._render_gmc_feed().encode())

    def test_required_fields_on_every_item(self):
        self.update_items()

        for product, item in self.items.items():
            self.assertEqual('new', item['condition'], product.display_name)
            self.assertTrue(item['description'], product.display_name)
            self.assertIn(item['availability'], ('in stock', 'out of stock'), product.display_name)

    def test_description_from_ecommerce_description(self):
        self.update_items()

        self.assertEqual("Rich marbling, best grilled.", self.items[self.steak]['description'])

    def test_description_falls_back_to_title(self):
        self.update_items()

        self.assertEqual(self.items[self.blanket]['title'], self.items[self.blanket]['description'])

    def test_description_falls_back_to_sales_description(self):
        self.blanket.description_sale = "Soft wool blanket"

        self.update_items()

        self.assertEqual("Soft wool blanket", self.items[self.blanket]['description'])

    def test_availability_from_template_ribbon(self):
        self.product_template_sofa.website_ribbon_id = self.ribbon_out

        self.update_items()

        self.assertEqual('out of stock', self.red_sofa_item['availability'])
        self.assertEqual('out of stock', self.blue_sofa_item['availability'])
        self.assertEqual('in stock', self.items[self.blanket]['availability'])

    def test_availability_from_variant_ribbon(self):
        self.blue_sofa.variant_ribbon_id = self.ribbon_out

        self.update_items()

        self.assertEqual('in stock', self.red_sofa_item['availability'])
        self.assertEqual('out of stock', self.blue_sofa_item['availability'])

    def test_availability_other_ribbon_is_in_stock(self):
        self.product_template_sofa.website_ribbon_id = self.ribbon_sale

        self.update_items()

        self.assertEqual('in stock', self.red_sofa_item['availability'])

    def test_availability_ignores_quantity_when_sold_out_of_stock(self):
        self.blanket.write({'is_storable': True, 'allow_out_of_stock_order': True})

        self.update_items()

        self.assertEqual('in stock', self.items[self.blanket]['availability'])

    def test_brand_from_attribute(self):
        self.update_items()

        self.assertEqual("Global Meat", self.items[self.steak]['brand'])
        self.assertNotIn('brand', self.items[self.blanket])

    def test_rendered_xml(self):
        self.steak_tmpl.website_ribbon_id = self.ribbon_out

        gmc_xml = self.render_feed()

        steak = gmc_xml.xpath(f'//item[g:id="{self.steak.id}"]', namespaces=G)[0]
        self.assertEqual('new', steak.findtext('g:condition', namespaces=G))
        self.assertEqual('out of stock', steak.findtext('g:availability', namespaces=G))
        self.assertEqual("Global Meat", steak.findtext('g:brand', namespaces=G))
        self.assertEqual("Rich marbling, best grilled.", steak.findtext('g:description', namespaces=G))
        for item in gmc_xml.xpath('//item'):
            self.assertEqual('new', item.findtext('g:condition', namespaces=G))
            self.assertTrue(item.findtext('g:description', namespaces=G))
        self.assertFalse(
            gmc_xml.xpath(f'//item[g:id="{self.blanket.id}"]/g:brand', namespaces=G),
            "No empty brand tag for a product without brand",
        )

    def test_default_out_of_stock_ribbons(self):
        sold_out = self.env['product.ribbon'].create({'name': "Sold out"})

        feed = self.env['product.feed'].create({'name': "Meta", 'website_id': self.website.id})

        self.assertIn(self.ribbon_out, feed.out_of_stock_ribbon_ids)
        self.assertIn(sold_out, feed.out_of_stock_ribbon_ids)
        self.assertNotIn(self.ribbon_sale, feed.out_of_stock_ribbon_ids)

    def test_product_change_resets_cache(self):
        self.gmc_feed.cache_expiry = fields.Datetime.add(fields.Datetime.now(), days=1)

        self.steak_tmpl.website_ribbon_id = self.ribbon_out

        self.assertLess(self.gmc_feed.cache_expiry, fields.Datetime.now())

    def test_variant_change_resets_cache(self):
        self.gmc_feed.cache_expiry = fields.Datetime.add(fields.Datetime.now(), days=1)

        self.blue_sofa.variant_ribbon_id = self.ribbon_out

        self.assertLess(self.gmc_feed.cache_expiry, fields.Datetime.now())

    def test_unrelated_change_keeps_cache(self):
        expiry = fields.Datetime.add(fields.Datetime.now(), days=1)
        self.gmc_feed.cache_expiry = expiry

        self.steak_tmpl.website_sequence = 99

        self.assertEqual(expiry, self.gmc_feed.cache_expiry)

    def test_ribbon_setting_change_resets_cache(self):
        self.gmc_feed.cache_expiry = fields.Datetime.add(fields.Datetime.now(), days=1)

        self.gmc_feed.out_of_stock_ribbon_ids |= self.ribbon_sale

        self.assertLess(self.gmc_feed.cache_expiry, fields.Datetime.now())
