from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestLoginSocialFirst(HttpCase):
    """Sign-in and sign-up pages: Google and Facebook first, then the email form."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].get_current_website()
        cls.website.write({'login_social_first': True, 'auth_signup_uninvited': 'b2c'})
        cls.env['auth.oauth.provider'].search([]).enabled = False
        for xmlid in ('auth_oauth.provider_google', 'auth_oauth.provider_facebook'):
            cls.env.ref(xmlid).write({'enabled': True, 'client_id': 'test-client'})

    def _page(self, url):
        self.authenticate(None, None)
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_login_page(self):
        page = self._page('/web/login')
        self.assertIn('o_login_social', page)
        self.assertIn('Sign in with', page)
        self.assertLess(page.index('o_login_social_btn'), page.index('name="login"'), "buttons before the email")
        self.assertLess(page.index('o_google_provider'), page.index('o_facebook_provider'), "Google first")
        self.assertNotIn('Sign in with Google', page, "not again under the form")
        self.assertIn('o_login_compact', page)

    def test_signup_page(self):
        page = self._page('/web/signup')
        self.assertIn('Sign up with', page)
        self.assertLess(page.index('o_login_social_btn'), page.index('name="name"'), "buttons before the name")
        self.assertNotIn('Sign in with Facebook', page)

    def test_switched_off(self):
        self.website.login_social_first = False
        page = self._page('/web/login')
        self.assertNotIn('o_login_social', page)
        self.assertIn('Sign in with Google', page, "the standard buttons under the form")
