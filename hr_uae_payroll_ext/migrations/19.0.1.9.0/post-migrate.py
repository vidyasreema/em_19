from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Bonuses and deductions had a fixed type (adjustment_type); they now point to
    a type record. The old column is kept by the ORM: map it to the starter types."""
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'hr_payroll_adjustment' AND column_name = 'adjustment_type'
    """)
    if cr.fetchone():
        cr.execute("""
            UPDATE hr_payroll_adjustment adjustment
               SET type_id = data.res_id
              FROM ir_model_data data
             WHERE data.module = 'hr_uae_payroll_ext'
               AND data.model = 'hr.payroll.adjustment.type'
               AND data.name = 'adjustment_type_' || adjustment.adjustment_type
               AND adjustment.type_id IS NULL
        """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.payroll.adjustment.type'].search([])._uae_setup_accounts()
