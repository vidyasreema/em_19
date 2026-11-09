{
    'name': 'Employee Portal: Requests',
    'version': '19.0.1.1.0',
    'category': 'Human Resources',
    'summary': 'Employees raise HR requests (certificates, letters, expense claims, changes) from the employee portal',
    'description': """
Employees raise any kind of request from their portal profile. Each kind is an
Approval Type of the Approvals app ticked "Available in employee portal"; HR
admins approve or refuse them, with a note and reply documents, from the portal
HR dashboard or in the Approvals app.
    """,
    'depends': ['hr_employee_portal', 'approvals'],
    'data': [
        'data/approval_category_data.xml',
        'views/approval_category_views.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'hr_employee_portal_requests/static/src/scss/portal_requests.scss',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
