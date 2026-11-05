import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Raw Material Category became Raw Material Categories (one category
    to many). Carry over the category already chosen on each POS, so the
    raw material popup keeps listing the same products after the upgrade.

    Odoo leaves the old column in place when a field is removed, which is
    what makes it readable here."""
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'pos_config' AND column_name = 'raw_material_categ_id'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        INSERT INTO pos_config_raw_material_categ_rel (config_id, categ_id)
        SELECT c.id, c.raw_material_categ_id
          FROM pos_config c
          JOIN product_category pc ON pc.id = c.raw_material_categ_id
        ON CONFLICT DO NOTHING
    """)
    _logger.info("Raw Material Category carried over to Raw Material Categories on %s POS", cr.rowcount)
    cr.execute("ALTER TABLE pos_config DROP COLUMN raw_material_categ_id")
