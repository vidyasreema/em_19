# -*- coding: utf-8 -*-
import base64
from io import BytesIO

from odoo import api, fields, models

try:
    import qrcode
except ImportError:
    qrcode = None


class CatalogConfig(models.Model):
    _name = "catalog.config"
    _description = "Catalog Configuration"

    name = fields.Char(string="Configuration Name", required=True, default="Catalog Settings")
    active = fields.Boolean(default=True)

    # --- Branding / images (per record) ---
    logo = fields.Binary(string="Logo")
    cover_image = fields.Binary(string="Cover / Hero Image")

    # --- Contact block shown on the thank-you page ---
    company_address = fields.Text(
        string="Address",
        default="Shop 22, Meat Market, Mushrif Mall\nAbu Dhabi, U.A.E.",
    )
    phone = fields.Char(string="Phone", default="(02) 6393944")
    whatsapp = fields.Char(string="WhatsApp", default="0507179729")
    website = fields.Char(string="Website", default="ExcellenceMeats.com")
    instagram = fields.Char(string="Instagram", default="@thecut_by_em")
    delivery_note = fields.Char(string="Delivery Note", default="FREE DELIVERY   MIN AED 300")
    badges = fields.Text(
        string="Badges (one per line)",
        default="GRASS-FED\nNO HORMONES\nNO ANTIBIOTICS\nOMEGA-3",
        help="Each line becomes a pill badge on the product grid page.",
    )

    # --- QR ---
    qr_url = fields.Char(string="QR Link", default="https://ExcellenceMeats.com")
    qr_image = fields.Binary(string="QR Code", compute="_compute_qr_image", store=True)

    @api.depends("qr_url")
    def _compute_qr_image(self):
        """Generate a QR PNG locally from qr_url (no network call)."""
        for rec in self:
            if qrcode and rec.qr_url:
                qr = qrcode.QRCode(
                    border=1,
                    box_size=10,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                )
                qr.add_data(rec.qr_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#2c0e16", back_color="#f0e6d2").convert("RGB")
                buf = BytesIO()
                img.save(buf, format="PNG")
                rec.qr_image = base64.b64encode(buf.getvalue())
            else:
                rec.qr_image = False