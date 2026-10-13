from . import models


def _post_init_hook(env):
    # Drop the feed XML cached by the core module (kept up to 24 hours), so the
    # new fields are served right after the install.
    env['product.feed'].search([]).action_invalidate_cache()
