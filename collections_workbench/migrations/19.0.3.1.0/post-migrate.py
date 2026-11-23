def migrate(cr, version):
    """The statement email now carries the PDF: fix the wording of the
    installed template, unless someone already edited it."""
    cr.execute("""
        UPDATE mail_template t
           SET body_html = jsonb_set(t.body_html, '{en_US}', to_jsonb(
                   replace(t.body_html->>'en_US', 'Please find below your statement',
                           'Please find attached your statement')))
          FROM ir_model_data d
         WHERE d.model = 'mail.template' AND d.res_id = t.id
           AND d.module = 'collections_workbench' AND d.name = 'mail_template_soa'
           AND t.body_html->>'en_US' LIKE '%%Please find below your statement%%'
    """)
