import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Same-day orders also get the delivery time popup (user request, 2026-10-21)
    cr.execute("UPDATE delivery_carrier SET show_popup_scenario_1 = TRUE WHERE show_popup_scenario_1 IS NOT TRUE")
    _logger.info("Same-day popup switched on for %s delivery methods", cr.rowcount)
