from . import controllers
from . import models


def _ep_link_document_fields(env):
    env['hr.employee.document.type']._ep_link_default_fields()
