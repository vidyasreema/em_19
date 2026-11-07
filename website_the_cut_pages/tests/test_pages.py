from odoo import Command
from odoo.tests import HttpCase, tagged

from odoo.addons.website_the_cut_pages.models.website import (
    HOMEPAGE_DESCRIPTION, HOMEPAGE_TITLE, cut_local_phone, cut_time,
)


@tagged('post_install', '-at_install')
class TestTheCutPages(HttpCase):
    """BRD-2026-10-CONTENT-PAGES, acceptance criteria 1-4, 10 and 11."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env.ref('website.default_website')
        cls.cur = cls.website.company_id.currency_id.name  # AED on The Cut
        cls.website.write({
            'cut_pages_enabled': True,
            'homepage_url': False,
            'journey_whatsapp_number': '+971 50 717 9729',
        })
        cls.website.company_id.partner_id.write({
            'phone': '+971 2 639 3944', 'street': 'Shop No. 22', 'street2': 'Meat Market, Mushrif Mall',
            'city': 'Abu Dhabi',
        })
        Store = cls.env['store.settings']
        Store.search([]).unlink()
        Store.create({'website_id': cls.website.id, 'shop_opening_time': 9.0, 'shop_closing_time': 22.0})

        cls.env['delivery.carrier'].search([]).is_published = False
        def method(name, area, price, **values):
            # Each method has its own delivery product: the fixed price is the product's price
            product = cls.env['product.product'].create({
                'name': name, 'type': 'service', 'taxes_id': [Command.clear()]})
            return cls.env['delivery.carrier'].create({
                'name': name, 'cut_area': area, 'product_id': product.id, 'delivery_type': 'fixed',
                'fixed_price': price, 'is_published': True, 'website_id': cls.website.id, **values,
            })
        cls.island = method('Abu Dhabi Island delivery', 'abu_dhabi', 40.0, cut_website_name='Abu Dhabi Island',
                            free_over=True, amount=400.0, enable_same_day_delivery=True,
                            promise_same_day_cutoff=19.0, promise_same_day_hours=3.0)
        cls.off_island = method('Outside Abu Dhabi Island Delivery', 'abu_dhabi', 55.0,
                                cut_website_name='Abu Dhabi, off the island', cut_website_note='For example Masdar City',
                                free_over=True, amount=400.0, enable_same_day_delivery=True,
                                promise_same_day_cutoff=19.0, promise_same_day_hours=3.0)
        cls.uae = method('Delivery Fee', 'uae', 55.0, cut_website_name='Rest of the UAE', free_over=True,
                         amount=800.0, enable_same_day_delivery=False, promise_next_day_from=12.0)
        cls.pickup = method('Pick up in store', 'pickup', 0.0, cut_website_name='Pickup from our shop',
                            cut_website_note='Mushrif Mall', enable_same_day_delivery=True,
                            promise_same_day_cutoff=21.0, promise_same_day_hours=1.0)

    def _page(self, url):
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200, url)
        return response.text

    def test_formats(self):
        self.assertEqual(cut_time(19.0), '7 PM')
        self.assertEqual(cut_time(19.5), '7:30 PM')
        self.assertEqual(cut_time(12.0), '12 PM')
        self.assertEqual(cut_time(0.0), '12 AM')
        self.assertEqual(cut_local_phone('+971 50 717 9729'), '0507179729')
        self.assertEqual(self.website._cut_amount(400.0), f'{self.cur} 400')
        self.assertEqual(self.website._cut_amount(40.005), f'{self.cur} 40.01')

    def test_fee_with_vat(self):
        """The fee as the checkout shows it: 38.10 + 5% VAT = AED 40.01."""
        self.website.show_line_subtotals_tax_selection = 'tax_included'
        self.island.product_id.taxes_id = self.env['account.tax'].create({'name': 'VAT 5%', 'amount': 5.0})
        self.island.fixed_price = 38.1
        self.assertEqual(self.website._cut_fee(self.island), f'{self.cur} 40.01')

    def test_homepage(self):
        page = self._page('/')
        self.assertIn('EVERY CUT HAS A STORY', page)
        self.assertIn('ORDER BEFORE 7 PM', page)
        self.assertIn('within 3 hours', page)
        self.assertIn(f'{self.cur} 40 on Abu Dhabi Island and {self.cur} 55 everywhere else.', page)
        self.assertIn(f'Free above {self.cur} 400 in Abu Dhabi and above {self.cur} 800 in the rest of the UAE.', page)
        self.assertIn('Pickup from our shop is always free.', page)
        self.assertIn(f'ABOVE {self.cur} 400', page, "Chapter 03")
        self.assertIn('0507179729', page, "footer: WhatsApp")
        self.assertIn('026393944', page, "footer: landline")
        self.assertIn('tc-header', page)
        self.assertNotIn('id="top"', page, "the previous header is replaced")

    def test_01_cutoff_change(self):
        """Acceptance 1: 6 PM everywhere, with no text edited."""
        (self.island | self.off_island).promise_same_day_cutoff = 18.0
        for url in ('/', '/delivery', '/about-us', '/shop'):
            page = self._page(url).replace('\N{NO-BREAK SPACE}', ' ')
            self.assertIn('6 PM', page, url)
            self.assertNotIn('7 PM', page, url)

    def test_02_fee_change(self):
        """Acceptance 2: the Delivery page and the FAQ show AED 45."""
        self.island.fixed_price = 45.0
        self.assertIn(f'{self.cur} 45', self._page('/delivery'))
        self.assertIn(f'{self.cur} 45 on Abu Dhabi Island', self._page('/'))

    def test_03_threshold_change(self):
        """Acceptance 3: the table, the FAQ and the homepage show the new amount."""
        self.island.amount = 500.0
        self.assertIn(f'FREE ABOVE {self.cur} 500', self._page('/delivery'))
        home = self._page('/')
        self.assertIn(f'Free above {self.cur} 500 in Abu Dhabi', home)
        self.assertIn(f'ABOVE {self.cur} 500', home)

    def test_04_empty_value_hidden(self):
        """Acceptance 4: a sentence whose value is empty is hidden, not shown incomplete."""
        self.website.journey_whatsapp_number = False
        page = self._page('/delivery')
        self.assertNotIn('Call or WhatsApp us on', page)
        self.assertIn('Contact us before your order leaves for delivery', page)
        (self.island | self.off_island).enable_same_day_delivery = False
        home = self._page('/')
        self.assertNotIn('ORDER BEFORE', home)
        self.assertNotIn('orders placed before', home)

    def test_delivery_table(self):
        page = self._page('/delivery')
        for text in ('ABU DHABI ISLAND', 'ABU DHABI, OFF THE ISLAND', 'For example Masdar City', 'REST OF THE UAE',
                     'PICKUP FROM OUR SHOP', 'Within 3 hours, orders before 7 PM', 'Orders before 9 PM',
                     'In the afternoon', 'ALWAYS FREE', 'Our shop is open 9 AM to 10 PM, every day.'):
            self.assertIn(text, page)
        self.assertEqual(page.count('class="tc-delivery-row"'), 4)
        # A new method appears on its own
        self.island.copy({'name': 'Sharjah', 'cut_website_name': 'Sharjah', 'is_published': True,
                          'product_id': self.island.product_id.copy().id})
        self.assertEqual(self._page('/delivery').count('class="tc-delivery-row"'), 5)

    def test_product_page_delivery_line(self):
        """Annex 3B, 3.1: the empty area of the product page gets the delivery line."""
        product = self.env['product.template'].create({
            'name': 'Wagyu Ribeye', 'list_price': 100.0, 'is_published': True, 'website_id': self.website.id})
        line = 'Same-day delivery in Abu Dhabi for orders before 7 PM · Free pickup from our shop'
        self.assertIn(line, self._page(product.website_url))
        (self.island | self.off_island).promise_same_day_cutoff = 18.0
        self.assertIn('orders before 6 PM', self._page(product.website_url))
        self.pickup.is_published = False
        self.assertNotIn('Free pickup', self._page(product.website_url))

    def test_10_privacy_collapsed(self):
        """Acceptance 10: the eight sections are collapsed and open when clicked."""
        page = self._page('/privacy')
        self.assertEqual(page.count('<details class="tc-policy-section"'), 8)
        self.assertNotIn('<details class="tc-policy-section" open', page)

    def test_11_homepage_description(self):
        """Acceptance 11: title and description of the homepage in Google."""
        self.env['website.page'].search([('url', '=', '/')]).website_meta_description = False
        self.env['website']._cut_set_homepage_seo()
        page = self._page('/')
        self.assertIn('<title>%s</title>' % HOMEPAGE_TITLE.replace('&', '&amp;'), page)
        self.assertIn(HOMEPAGE_DESCRIPTION, page)

    def test_terms_same_link(self):
        page = self._page('/terms')
        self.assertIn('TERMS OF SALE', page)
        self.assertIn('NO RETURNS', page)
        self.assertIn('Shop No. 22, Meat Market, Mushrif Mall, Abu Dhabi, UAE', page)

    def test_odoo_pages_get_header_and_footer(self):
        page = self._page('/shop')
        self.assertIn('tc-header', page)
        self.assertIn('o_wsale_my_cart', page, "the cart stays in the header")
        self.assertIn('<a href="/">HOME</a>', page, "HOME tab first (Annex 3B, 2.1)")
        self.assertLess(page.index('<a href="/">HOME</a>'), page.index('<a href="/shop">SHOP</a>'))
        self.assertNotIn('fa-home', page, "no small home icon")
        self.assertIn('tc-footer', page)
        self.assertIn('tc-site', page, "colours, fonts and buttons of the new pages")
        self.assertIn('Same-day delivery in Abu Dhabi for orders before 7\N{NO-BREAK SPACE}PM', page, "Deliver to bar")

    def test_shop_card_photo_size(self):
        self.env['product.template'].create({'name': 'Photo size check', 'is_published': True, 'sale_ok': True})
        page = self._page('/shop?search=Photo+size+check')
        self.assertIn('/image_512', page, "the cards load the 512 px photos (speed)")
        self.assertNotIn('/image_1024', page)

    def test_about_halal(self):
        page = self._page('/about-us')
        self.assertIn('حلال</span>HALAL', page, "What We Sell: the halal line")

    def test_contact_page_top(self):
        page = self._page('/contactus')
        self.assertIn('tc-contact-hero', page)
        self.assertIn('CONTACT US', page)
        self.assertIn('WHATSAPP 0507179729', page)
        self.assertIn('CALL 026393944', page)
        self.assertIn('Our shop is open 9 AM to 10 PM, every day.', page)
        self.assertIn('s_website_form', page, "the Odoo form stays")
        self.assertNotIn('tc-contact-hero', self._page('/shop'))

    def test_switch_off(self):
        self.website.cut_pages_enabled = False
        self.assertNotIn('EVERY CUT HAS A STORY', self._page('/'))
        shop = self._page('/shop')
        self.assertNotIn('tc-header', shop)
        self.assertNotIn('tc-site', shop)
        self.assertNotIn('tc-contact-hero', self._page('/contactus'))
        self.assertEqual(self.url_open('/delivery').status_code, 404)
