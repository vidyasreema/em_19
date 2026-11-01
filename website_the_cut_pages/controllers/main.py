from odoo import http
from odoo.http import request

from odoo.addons.account.controllers.terms import TermsController
from odoo.addons.website.controllers.main import Website


def cut_render(template, url):
    """A page of The Cut, with the page record of its URL (title and description
    in Google, link previews) when there is one."""
    website = request.website
    page = request.env['website.page'].sudo().search(
        [('url', '=', url)] + website.website_domain(), order='website_id', limit=1)
    return request.render(template, {'main_object': page or website, 'tc': website._cut_values()})


def sitemap_delivery(env, rule, qs):
    if env['website'].get_current_website().cut_pages_enabled and (not qs or qs.lower() in '/delivery'):
        yield {'loc': '/delivery'}


class TheCutHomepage(Website):

    @http.route()
    def index(self, **kw):
        website = request.website
        if website.cut_pages_enabled and website._get_cached('homepage_url') in (False, None, '', '/'):
            return cut_render('website_the_cut_pages.page_home', '/')
        return super().index(**kw)


class TheCutTerms(TermsController):

    @http.route()
    def terms_conditions(self, **kwargs):
        # Same link as before: the checkout and Google Merchant Center read it
        if request.website.cut_pages_enabled:
            return cut_render('website_the_cut_pages.page_terms', '/terms')
        return super().terms_conditions(**kwargs)


class TheCutPages(http.Controller):

    def _cut_page(self, template, url):
        """The page of The Cut, or the previous page of this URL when they are switched off."""
        if request.website.cut_pages_enabled:
            return cut_render(template, url)
        page = request.env['ir.http']._serve_page()
        if not page:
            raise request.not_found()
        return page

    @http.route('/delivery', type='http', auth='public', website=True, sitemap=sitemap_delivery)
    def cut_delivery(self, **kwargs):
        return self._cut_page('website_the_cut_pages.page_delivery', '/delivery')

    # The website pages of these URLs are already in the sitemap
    @http.route('/about-us', type='http', auth='public', website=True, sitemap=False)
    def cut_about(self, **kwargs):
        return self._cut_page('website_the_cut_pages.page_about', '/about-us')

    @http.route('/privacy', type='http', auth='public', website=True, sitemap=False)
    def cut_privacy(self, **kwargs):
        return self._cut_page('website_the_cut_pages.page_privacy', '/privacy')
