import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # "You have a new coupon" party: only for coupons of the last 7 days, not
    # for every coupon customers already had before this version
    cr.execute("""
        UPDATE loyalty_card
           SET journey_celebrated = TRUE
         WHERE create_date < now() - interval '7 days'
    """)
    _logger.info("%s older coupons marked as already shown", cr.rowcount)
