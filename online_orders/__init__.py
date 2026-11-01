from . import models
from . import wizard


# Groups of other apps whose users must keep seeing the product cost, when
# those apps are installed (they are not dependencies of this module).
OPTIONAL_COST_GROUPS = [
    'purchase.group_purchase_user',
    'mrp.group_mrp_user',
    'point_of_sale.group_pos_user',
]


def _online_orders_post_init(env):
    cost_group = env.ref('online_orders.group_product_cost')
    for xmlid in OPTIONAL_COST_GROUPS:
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            group.implied_ids = [(4, cost_group.id)]
    env['sale.order']._online_orders_init_existing_orders()


def _online_orders_uninstall(env):
    """Release the stages (orders point to them) and restore the Contacts action."""
    env.cr.execute("UPDATE sale_order SET stage_id = NULL WHERE stage_id IS NOT NULL")
    action = env.ref('contacts.action_contacts', raise_if_not_found=False)
    if action:
        action.context = "{'default_is_company': True}"
