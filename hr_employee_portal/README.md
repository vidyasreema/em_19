# The Cut Employee Portal (Odoo 19)

Branded login, employee self-service and an HR dashboard, in the design of the
website (The Cut red #7E1416 on cream, Anton headings, Figtree text, The Cut pattern).

## Pages
| URL | Who | What |
|---|---|---|
| /web/login | Everyone | Branded sign-in page (add ?debug=1 for Odoo's standard login) |
| /my | Portal employees | Redirects to /my/employee |
| /my/employee | Employee | Staff card, summary, details, document expiry, leave, payslips |
| /my/employee/leaves | Employee | Balances, leave request form, request history |
| /my/employee/payslips | Employee | Confirmed payslips with PDF download (needs hr_payroll) |
| /my/hr/dashboard | Admin | Headcount, approvals, expiring documents, away today, directory |
| /my/hr/employee/<id> | Admin | Any employee's profile and recent leave |

Desktop shows a sidebar; phones get the wave header with tab buttons.

## Setup
1. Copy the folder into your addons path, update the apps list, install
   "Employee Self-Service Portal". If it was installed before, upgrade it.
2. For each employee: grant portal access to their contact and set that user in the
   employee's Related User field.
3. Admins: backend HR Managers get the dashboard automatically. Anyone else: add the
   "Employee Portal: HR Admin" group (developer mode, Settings > Users & Companies > Groups).
4. Optional: replace static/src/img/the_cut_logo.png with the original white logo file.

## Notes
- The login page applies to all users, including internal users. Debug mode shows
  Odoo's standard login, which is useful if you ever need the database selector.
- "Forgot password?" appears when password reset is enabled
  (Settings > Permissions > Password Reset).
- Employees change their password from the sidebar (opens Odoo's /my/security page).

## Verify on your Odoo 19 instance
- web.login is swapped through the controller (`response.template`). If another module
  also replaces the login template, check which one wins.
- Field names in PROFILE_SECTIONS and DOCUMENT_FIELDS (missing ones are skipped).
- The join date fields in `_ep_join_date` (contract data lives on employee versions in 19).
- Payslip report XML ID `hr_payroll.action_report_payslip` and states `done`/`paid`.

## Security model
Portal users get no access rights. Every read happens server-side with sudo(), scoped to
the logged-in user's own employee; admin routes check the group and return 404 otherwise.
Payslip PDFs check ownership (or admin + company) before rendering.
