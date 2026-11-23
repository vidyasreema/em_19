from . import models
from . import wizard


def _post_init_hook(env):
    """Link records created by the data files with tags that already exist
    in the database, reusing them by name instead of creating duplicates."""
    Tag = env['res.partner.category']
    agreement = Tag.search([('name', '=ilike', 'Agreement: Cheque')], limit=1)
    if not agreement:
        agreement = Tag.create({'name': 'Agreement: Cheque', 'color': 10})
    pipeline = env.ref('collections_workbench.pipeline_agreement', raise_if_not_found=False)
    if pipeline and not pipeline.tag_id:
        pipeline.tag_id = agreement
    env['res.company'].search([])._collection_init_default_settings()
