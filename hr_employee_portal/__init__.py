from . import controllers
from . import models


def _post_init_hook(env):
    env['hr.leave.type']._ep_enable_used_types()
