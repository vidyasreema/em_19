# -*- coding: utf-8 -*-
import base64
import io
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import flagpy as _flagpy
except Exception:
    _flagpy = None
try:
    import pycountry as _pycountry
except Exception:
    _pycountry = None

ORIGIN_ATTR_NAME = "Country of Origin"


class CatalogBuilder(models.Model):
    _name = "catalog.builder"
    _description = "Product Catalog"
    _order = "date desc, id desc"

    name = fields.Char(string="Reference", required=True,
                       copy=False, default="New", readonly=True)
    date = fields.Date(string="Date", default=fields.Date.context_today,
                       required=True)
    config_id = fields.Many2one("catalog.config", string="Configuration")
    line_ids = fields.One2many("catalog.line", "catalog_id",
                               string="Catalog Lines")
    line_count = fields.Integer(compute="_compute_line_count")
    state = fields.Selection(
        [("draft", "Draft"), ("generated", "Generated")],
        string="Status", default="draft", required=True, copy=False)

    pdf_file = fields.Binary(string="Catalog PDF", readonly=True, copy=False)
    pdf_filename = fields.Char(string="PDF Filename", readonly=True, copy=False)

    # --- Selection filters (the main way to build the catalog) ---
    category_ids = fields.Many2many(
        "product.category", "catalog_builder_categ_rel",
        "catalog_id", "categ_id",
        string="Animals (Categories)",
        help="Beef, Lamb, Venison... Leave empty to include all categories. "
             "Select MULTIPLE categories here if you want them all in one "
             "catalog - Load Products includes every one of them at once.")
    origin_value_ids = fields.Many2many(
        "product.attribute.value", "catalog_builder_origin_rel",
        "catalog_id", "value_id",
        string="Countries of Origin",
        domain=[("attribute_id.name", "=", ORIGIN_ATTR_NAME)],
        help="Australian, New Zealand... Leave empty to include all origins. "
             "Select MULTIPLE countries here if you want them all in one "
             "catalog - Load Products includes every one of them at once.")

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "catalog.builder") or "New"
        return super().create(vals_list)

    # ------------------------------------------------------------------ #
    #  Load products by Category + Country of Origin (AND)
    # ------------------------------------------------------------------ #
    def _append_products(self, products):
        """Add products as new lines, skipping ones already present."""
        self.ensure_one()
        existing = set(self.line_ids.mapped("product_id").ids)
        next_seq = max(self.line_ids.mapped("sequence") or [0])
        new_lines = []
        for product in products:
            if product.id in existing:
                continue
            next_seq += 10
            new_lines.append((0, 0, {
                "sequence": next_seq,
                "product_id": product.id,
                "name": product.display_name,
                "price": product.list_price,
                # NOTE: switched from image_1920 -> image_256.
                # The report only ever displays this at ~150px height via CSS,
                # so storing/encoding the full 1920px image was pure overhead
                # (this was the main cause of slow PDF generation on large catalogs).
                "image": product.image_256,
                "description": product.description_sale or "",
            }))
        if new_lines:
            self.write({"line_ids": new_lines})
        return len(new_lines)

    def action_load_products(self):
        """Pick Category + Country -> list matching products as lines.
        Empty filters = all products. Filters combine with AND
        (and OR across multiple countries, and OR across multiple
        categories - both fields are many2many). Want Deer AND Lamb in
        one catalog? Select both categories before clicking this button.

        IMPORTANT: this REPLACES the current catalog lines with exactly
        what matches the filters right now, rather than accumulating
        across separate clicks. Previously this method only ever
        appended, so clicking Load Products again with a different
        category/country selection left every earlier selection's
        products still sitting in the catalog (e.g. filtering to
        Deer + New Zealand still showed Lamb and Angus products left
        over from an earlier click on this same record). Replacing
        keeps what's on screen always equal to the current filter
        selection - no stale leftovers, no confusion about what will
        actually print."""
        self.ensure_one()
        domain = []
        if self.category_ids:
            domain.append(("categ_id", "child_of", self.category_ids.ids))
        if self.origin_value_ids:
            domain.append(
                ("product_template_attribute_value_ids."
                 "product_attribute_value_id", "in", self.origin_value_ids.ids))
        products = self.env["product.product"].search(domain)
        if not products:
            raise UserError(_("No products match the selected filters."))

        # Replace, don't accumulate: wipe whatever was here before, then
        # add exactly the current filter's matches.
        self.line_ids.unlink()
        added = self._append_products(products)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Load Products"),
                "message": _("Catalog now has %s product(s) matching your "
                             "filters.") % added,
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": self._name,
                    "res_id": self.id,
                    "view_mode": "form",
                    "views": [(False, "form")],
                    "target": "current",
                },
            },
        }

    # ------------------------------------------------------------------ #
    #  Preview / Print
    # ------------------------------------------------------------------ #
    def action_preview(self):
        """Open the PDF in a browser tab. Nothing saved."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Add at least one product before previewing."))
        return {
            "type": "ir.actions.act_url",
            "url": "/report/pdf/the_cut_catalog.action_report_catalog/%s" % self.id,
            "target": "new",
        }

    def action_print_catalog(self):
        """Generate the PDF, store it on the record, set state to Generated.
        Can be run again to regenerate/overwrite."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Add at least one product before printing."))
        pdf_content, _ct = self.env["ir.actions.report"]._render_qweb_pdf(
            "the_cut_catalog.action_report_catalog", res_ids=self.ids)
        filename = "%s.pdf" % (self.name or "Catalog")
        self.write({
            "pdf_file": base64.b64encode(pdf_content),
            "pdf_filename": filename,
            "state": "generated",
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Print Catalog"),
                "message": _("PDF generated and saved. You can download it below."),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": self._name,
                    "res_id": self.id,
                    "view_mode": "form",
                    "views": [(False, "form")],
                    "target": "current",
                },
            },
        }

    def action_reset_draft(self):
        self.write({"state": "draft"})

    # ------------------------------------------------------------------ #
    #  Grouping for the report: animal (category) -> country -> lines
    # ------------------------------------------------------------------ #
    def _leaf_category_name(self, categ):
        """Return just the animal name, e.g. 'All / PoS / beef' -> 'BEEF'."""
        if not categ:
            return "OTHER"
        return (categ.name or "").upper()

    def get_report_sections(self):
        """Group lines: animal (category) -> country (origin) -> lines.
        Returns a list ready for the QWeb template."""
        self.ensure_one()
        lines = self.line_ids

        cats = lines.mapped("category_id").sorted(lambda c: (c.name or ""))
        ordered = list(cats)
        if lines.filtered(lambda l: not l.category_id):
            ordered.append(self.env["product.category"])  # empty -> "OTHER"

        sections = []
        for categ in ordered:
            if categ:
                sec_lines = lines.filtered(lambda l: l.category_id == categ)
            else:
                sec_lines = lines.filtered(lambda l: not l.category_id)
            if not sec_lines:
                continue

            origins = sec_lines.mapped("origin_value_id").sorted(
                lambda v: (v.sequence, v.id))

            # Build a flat, ordered list of blocks: an origin-header block
            # followed by one card block per product line in that origin.
            blocks = []
            for origin in origins:
                grp = sec_lines.filtered(lambda l: l.origin_value_id == origin)
                flag = next((l.flag_image for l in grp if l.flag_image), False)
                blocks.append({
                    "type": "header",
                    "name": origin.name,
                    "count": len(grp),
                    "flag_image": flag,
                })
                for line in grp:
                    blocks.append({"type": "card", "line": line})

            unspecified = sec_lines.filtered(lambda l: not l.origin_value_id)
            if unspecified:
                blocks.append({
                    "type": "header",
                    "name": "Unspecified origin",
                    "count": len(unspecified),
                    "flag_image": False,
                })
                for line in unspecified:
                    blocks.append({"type": "card", "line": line})

            pages = self._paginate_blocks(blocks)

            # Category image first, then fall back to a product image.
            hero = False
            if categ and categ.catalog_image:
                hero = categ.catalog_image
            if not hero:
                hero = next((l.image for l in sec_lines if l.image), False)

            sections.append({
                "title": self._leaf_category_name(categ),
                "count": len(sec_lines),
                "hero_image": hero,
                "pages": pages,
            })
        return sections

    @staticmethod
    def _merge_card_blocks(page_blocks):
        """Collapse consecutive 'card' blocks on a page into a single
        'cards' block holding a list of lines, so the template can wrap
        consecutive cards in one shared grid container (side-by-side)
        while origin-header blocks stay separate on their own row."""
        merged = []
        current_lines = []
        for block in page_blocks:
            if block["type"] == "card":
                current_lines.append(block["line"])
            else:
                if current_lines:
                    merged.append({"type": "cards", "lines": current_lines})
                    current_lines = []
                merged.append(block)
        if current_lines:
            merged.append({"type": "cards", "lines": current_lines})
        return merged

    def _paginate_blocks(self, blocks, cards_per_page=12):
        """Pack a flat list of blocks (origin headers + product cards) into
        pages, capping each page at `cards_per_page` cards (matches the
        3-column x 4-row = 12 cards/page grid in the report template).

        Headers flow inline with the cards that follow them and do NOT
        force a page break by themselves - they only get pushed to a new
        page if the current page has already hit its card limit. This
        keeps pages tightly packed: if one origin group ends partway
        through a page, the next origin's cards continue filling that
        same page instead of jumping to a fresh page and leaving the
        rest of the previous page blank."""
        pages = []
        page = []
        card_count = 0
        for block in blocks:
            if block["type"] == "card":
                if card_count == cards_per_page:
                    pages.append(self._merge_card_blocks(page))
                    page = []
                    card_count = 0
                page.append(block)
                card_count += 1
            else:  # header block
                if card_count == cards_per_page:
                    pages.append(self._merge_card_blocks(page))
                    page = []
                    card_count = 0
                page.append(block)
        if page:
            pages.append(self._merge_card_blocks(page))
        return pages


class CatalogLine(models.Model):
    _name = "catalog.line"
    _description = "Catalog Line"
    _order = "sequence, id"

    catalog_id = fields.Many2one("catalog.builder", string="Catalog",
                                 required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one("product.product", string="Product")
    name = fields.Char(string="Display Name")
    price = fields.Float(string="Price")
    image = fields.Binary(string="Image")
    description = fields.Char(string="Description")
    origin = fields.Char(string="Origin (manual override)")

    category_id = fields.Many2one(
        "product.category", string="Animal (Category)",
        compute="_compute_from_product", store=True)
    origin_value_id = fields.Many2one(
        "product.attribute.value", string="Origin (Attribute)",
        compute="_compute_from_product", store=True)
    origin_text = fields.Char(
        string="Origin (text)", compute="_compute_from_product", store=True)
    flag_image = fields.Binary(
        string="Flag", compute="_compute_from_product", store=True)

    # Common adjective / short forms -> proper country name for pycountry
    _COUNTRY_NAME_FIXES = {
        "australian": "Australia",
        "aus": "Australia",
        "new zealand": "New Zealand",
        "nz": "New Zealand",
        "spanish": "Spain",
        "usa": "United States",
        "us": "United States",
        "american": "United States",
        "brazilian": "Brazil",
        "indian": "India",
        "uae": "United Arab Emirates",
    }

    @api.depends("product_id", "product_id.categ_id",
                 "product_id.product_template_attribute_value_ids", "origin")
    def _compute_from_product(self):
        for line in self:
            product = line.product_id
            line.category_id = product.categ_id.id if product else False

            origin_val = False
            if product:
                ptavs = product.product_template_attribute_value_ids
                match = ptavs.filtered(
                    lambda v: v.attribute_id.name == ORIGIN_ATTR_NAME)[:1]
                origin_val = match.product_attribute_value_id if match else False

            line.origin_value_id = origin_val.id if origin_val else False
            line.origin_text = (line.origin
                                or (origin_val.name if origin_val else False)
                                or False)
            # FIX: the flag must follow whatever text is actually being
            # displayed (origin_text - which already respects the manual
            # "origin" override), not the product's raw attribute value.
            # Previously this always used origin_val, so typing a manual
            # override changed the visible text but left the old flag
            # showing the product's original country.
            line.flag_image = line._flag_for_name(line.origin_text)

    @staticmethod
    def _flag_for_name(country_raw):
        """Render a PNG flag from a country name/adjective string."""
        if not (_flagpy and _pycountry and country_raw):
            return False
        raw = (country_raw or "").strip()
        if not raw:
            return False

        # 1) map common adjective/short forms to a proper country name
        country_name = CatalogLine._COUNTRY_NAME_FIXES.get(raw.lower())

        # 2) try exact, then fuzzy lookup in pycountry
        if not country_name:
            try:
                c = _pycountry.countries.get(name=raw)
                if not c:
                    c = _pycountry.countries.search_fuzzy(raw)[0]
                country_name = c.name
            except Exception:
                country_name = raw  # last resort: use the raw text

        try:
            pil = _flagpy.get_flag_img(country_name)
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue())
        except Exception as exc:
            _logger.warning("Catalog flag render failed for %r: %s", raw, exc)
            return False

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.name = line.product_id.display_name
                line.price = line.product_id.list_price
                # NOTE: switched from image_1920 -> image_256 (see _append_products
                # above for why: the report only displays this at ~150px height).
                line.image = line.product_id.image_256
                line.description = line.product_id.description_sale or ""