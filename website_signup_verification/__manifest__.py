{
    'name': 'Website Sign-up Verification',
    'version': '19.0.1.1.1',
    'category': 'Website/Website',
    'summary': 'The Cut: email code at sign-up, one account per customer, sign-up coupon rules',
    'description': """
        Website Sign-up Verification (Annex 3A)
        =======================================

        - Sign-up matches existing customers by email: an email with an account
          gets "You already have an account" (no error); a guest email is linked
          to its customer record (orders and addresses) once the code is entered;
          several records: the most recent one, the others are tagged for the
          daily check (merge them from Contacts).
        - Verification code by email (no-reply@), valid 10 minutes, with Resend.
          No account is created before the code is entered.
        - Google / Facebook: no code, the same matching.
        - A guest order placed later with the email of an account joins that
          account (My orders) when the account proved the email (code, Google /
          Facebook); otherwise its customer is tagged for the daily check.
        - Sign-up coupon: one programme with a fixed code, only for accounts
          activated by the code (or Google / Facebook), once per customer and
          per mobile number. Its rate and minimum drive the order page texts.

        Website > Configuration > Settings > "Verify sign-ups with a code"
        switches the sign-up part off; emptying "Sign-up coupon" switches off
        the coupon rules. Uninstalling the module removes everything.
    """,
    'author': 'Vidyasree',
    'website': 'https://thecutuae.com',
    'depends': [
        'website_purchase_journey',
        'auth_signup',
        'auth_oauth',
        'website_sale_loyalty',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
        'data/res_partner_category_data.xml',
        'data/loyalty_data.xml',
        'views/res_config_settings_views.xml',
        'views/signup_templates.xml',
        'views/order_templates.xml',
        'views/login_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_signup_verification/static/src/scss/login.scss',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
