{
    'name': 'Employee Self-Service Portal',
    'version': '19.0.2.3.1',
    'category': 'Human Resources',
    'summary': 'Branded login, employee self-service and HR dashboard for The Cut',
    'depends': ['portal', 'hr', 'hr_holidays'],
    'data': [
        'security/security.xml',
        'views/hr_leave_type_views.xml',
        'views/layout_templates.xml',
        'views/login_templates.xml',
        'views/portal_templates.xml',
        'views/admin_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'hr_employee_portal/static/src/scss/employee_portal.scss',
            'hr_employee_portal/static/src/js/employee_portal.js',
        ],
    },
    'post_init_hook': '_post_init_hook',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
