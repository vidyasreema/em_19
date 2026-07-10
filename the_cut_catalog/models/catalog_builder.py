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
        help="Beef, Lamb, Venison... Leave empty to include all categories.")
    origin_value_ids = fields.Many2many(
        "product.attribute.value", "catalog_builder_origin_rel",
        "catalog_id", "value_id",
        string="Countries of Origin",
        domain=[("attribute_id.name", "=", ORIGIN_ATTR_NAME)],
        help="Australian, New Zealand... Leave empty to include all origins.")

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
        categories - both fields are many2many).

        IMPORTANT: this REPLACES the current catalog lines with exactly
        what matches the filters right now, rather than accumulating
        across separate clicks. Previously this only ever appended, so
        clicking Load Products again with a different category/country
        selection left every earlier selection's products still sitting
        in the catalog. Replacing keeps what's on screen always equal
        to the current filter selection - no stale leftovers."""
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
        """Group lines: animal (category) -> country (origin) -> lines,
        then pack each category's origin groups into pages using the
        split-fill row-budget model. Each category keeps its own divider
        page and titled grid pages (as before); within a category, cards
        pack tightly - a group can split across pages so leftover space
        is always used, regardless of origin."""
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

            groups = []
            for origin in origins:
                grp = sec_lines.filtered(lambda l: l.origin_value_id == origin)
                flag = next((l.flag_image for l in grp if l.flag_image), False)
                groups.append({
                    "name": origin.name,
                    "count": len(grp),
                    "lines": grp,
                    "flag_image": flag,
                })
            unspecified = sec_lines.filtered(lambda l: not l.origin_value_id)
            if unspecified:
                groups.append({
                    "name": "Unspecified origin",
                    "count": len(unspecified),
                    "lines": unspecified,
                    "flag_image": False,
                })

            pages = self._pack_groups_into_pages(groups)

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

    # Report grid is tuned for 3 columns x 4 rows = 12 cards per page.
    # Modeled as "budget units" based on the actual CSS pixel heights:
    #   - a card row (incl. margins) is ~213px tall -> costs 1.0 unit
    #   - an origin-header bar (incl. margins/padding) is ~46px, plus the
    #     ~10px top padding added each time a new .cards block starts, for
    #     a combined ~56px -> costs ~0.27 units (56/213)
    # A full single-origin page (1 header + 4 rows) then costs
    # 0.27 + 4 = 4.27 units; the budget below (4.2) keeps a small safety
    # margin under that so nothing sits right at the edge. This lets
    # several small origin groups safely share a page - unlike counting
    # raw cards alone, this accounts for header height too, so nothing
    # overflows past the fixed page height and gets clipped.
    _PAGE_BUDGET_UNITS = 4.2
    _HEADER_COST_UNITS = 0.27
    _PAGE_MAX_CARDS = 12  # 4 rows x 3 columns, the largest a single page holds

    @staticmethod
    def _rows_for_count(count):
        """3 cards per row, rounded up."""
        return -(-count // 3)  # ceil division without importing math

    def _pack_groups_into_pages(self, groups):
        """Pack origin groups (header + cards each) into pages using the
        row-budget model above. An origin group's cards can be SPLIT
        across pages: if only part of a group fits in the space left on
        the current page, that part is placed there (with its header)
        and the rest continues on the next page (header repeated). This
        fills every bit of available space - e.g. if Spanish is on a
        page with room left over, some Unspecified-origin cards fill
        that room instead of the whole group jumping to a fresh page."""
        pages = []
        current_page = []
        current_cost = 0.0

        def header_block(grp):
            return {
                "type": "header",
                "name": grp["name"],
                "count": grp["count"],
                "flag_image": grp["flag_image"],
            }

        def flush():
            nonlocal current_page, current_cost
            if current_page:
                pages.append(current_page)
            current_page = []
            current_cost = 0.0

        for grp in groups:
            remaining = list(grp["lines"])
            while remaining:
                available = self._PAGE_BUDGET_UNITS - current_cost
                rows_avail = int(available - self._HEADER_COST_UNITS)
                if rows_avail < 1:
                    # Not enough room for the header plus at least one
                    # row of cards - start a fresh page.
                    flush()
                    available = self._PAGE_BUDGET_UNITS
                    rows_avail = int(available - self._HEADER_COST_UNITS)
                cards_avail = rows_avail * 3
                take = min(cards_avail, len(remaining))
                chunk = remaining[:take]
                remaining = remaining[take:]
                rows_used = self._rows_for_count(len(chunk))
                current_page.append(header_block(grp))
                current_page.append({"type": "cards", "lines": chunk})
                current_cost += self._HEADER_COST_UNITS + rows_used

        flush()
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