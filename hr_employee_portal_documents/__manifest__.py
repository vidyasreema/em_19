{
    'name': 'Employee Portal: Documents',
    'version': '19.0.1.1.0',
    'category': 'Human Resources',
    'summary': 'Employees upload their passport, visa, Emirates ID and other documents from the employee portal',
    'description': """
New employees upload their own documents (passport, visa, Emirates ID, work
permit, photo, certificates...) from the employee portal, with the document
number and expiry date. HR checks each upload, from the portal HR dashboard or
in Employees > Portal Documents: verifying it copies the file, number and
expiry date into the employee's profile; rejecting it sends a note back.
The list of documents is configurable in Employees > Configuration.
    """,
    'depends': ['hr_employee_portal'],
    'data': [
        'security/ir.model.access.csv',
        'security/hr_employee_document_security.xml',
        'data/hr_employee_document_type_data.xml',
        'views/hr_employee_document_views.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'hr_employee_portal_documents/static/src/scss/portal_documents.scss',
        ],
    },
    'post_init_hook': '_ep_link_document_fields',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
