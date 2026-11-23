from datetime import date, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CollectionsCommon


@tagged('post_install', '-at_install')
class TestFollowup(CollectionsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer.email = 'acme@example.com'
        cls.customer2.email = 'star@example.com'
        cls.inv_acme = cls._invoice(cls.customer, 1000.0, '2026-10-10')
        cls.inv_star = cls._invoice(cls.customer2, 2000.0, '2026-10-12')
        ref = cls.env.ref
        cls.collection = ref('collections_workbench.pipeline_collection')
        cls.claim = ref('collections_workbench.stage_claim')
        cls.reminder1 = ref('collections_workbench.stage_reminder_1')
        cls.hold = ref('collections_workbench.stage_credit_hold')
        cls.final = ref('collections_workbench.stage_final_notice')
        cls.partial = ref('collections_workbench.stage_partial')
        cls.legal = ref('collections_workbench.pipeline_legal')
        cls.blacklist = ref('collections_workbench.pipeline_blacklist')
        cls.vip_tag = cls.env['res.partner.category'].create({'name': 'VIP collections test'})
        cls.env.company.collection_vip_tag_ids = [(4, cls.vip_tag.id)]

    def _wizard(self, partners, **vals):
        ctx = {'default_partner_ids': partners.ids}
        return self.env['collection.followup.wizard'].with_context(ctx).create(vals)

    def _notes(self, partner, xmlid):
        cat = self.env.ref('collections_workbench.' + xmlid)
        return partner.collection_note_ids.filtered(lambda n: n.category_id == cat)

    # --- stage emails -------------------------------------------------------
    def test_stage_email_only_to_customer_not_followers(self):
        """Staff following the contact get no copy of the collection letter."""
        staff = self.env['res.partner'].create({'name': 'Office Staff', 'email': 'office@example.com'})
        self.customer.message_subscribe(partner_ids=staff.ids)
        self._wizard(self.customer, stage_id=self.claim.id).action_confirm()
        msg = self.customer.message_ids.filtered(lambda m: m.message_type == 'comment')[:1]
        self.assertEqual(msg.subtype_id, self.env.ref('mail.mt_comment'), "still shown in the Emails tab")
        self.assertEqual(msg.notification_ids.res_partner_id, self.customer)

    def test_stage_email_sent_and_logged(self):
        wiz = self._wizard(self.customer, stage_id=self.claim.id)
        self.assertEqual(wiz.send_mode, 'email')
        self.assertIn('1,000.00', wiz.body)
        self.assertIn('ACME Collections Test', wiz.subject)
        wiz.action_confirm()
        self.assertEqual(self.customer.collection_stage_id, self.claim)
        self.assertEqual(self.customer.collection_pipeline_id, self.collection)
        msg = self.customer.message_ids.filtered(lambda m: m.subject == wiz.subject)
        self.assertTrue(msg, "email posted on the customer card")
        self.assertIn(self.customer, msg.partner_ids)
        note = self._notes(self.customer, 'note_cat_email_sent')
        self.assertEqual(note.channel, 'email')
        self.assertEqual(note.user_id, self.env.user)
        self.assertEqual(note.stage_id, self.claim)

    def test_ac13_unreconciled_blocks_email(self):
        self._unreconciled_payment(self.customer, 100.0, '2026-11-01')
        wiz = self._wizard(self.customer, stage_id=self.claim.id)
        with self.assertRaises(UserError):
            wiz.action_confirm()
        self.assertFalse(self.customer.collection_stage_id)
        # recording without email stays available
        wiz = self._wizard(self.customer, stage_id=self.claim.id, send_mode='record', channel='call')
        wiz.action_confirm()
        self.assertEqual(self.customer.collection_stage_id, self.claim)

    def test_ac14_bulk_excludes_by_name_and_reason(self):
        no_email = self.env['res.partner'].create({'name': 'No Mail Co'})
        in_legal = self.env['res.partner'].create({'name': 'Court Co', 'email': 'court@example.com'})
        in_legal._collection_apply_stage(self.legal.stage_ids[:1], channel='other')
        partners = self.customer | self.customer2 | no_email | in_legal
        wiz = self._wizard(partners, stage_id=self.claim.id)
        self.assertIn('No email on the customer card', wiz.preview_html)
        self.assertIn('Legal Cases', wiz.preview_html)
        result = wiz.action_confirm()
        self.assertEqual(self.customer.collection_stage_id, self.claim)
        self.assertEqual(self.customer2.collection_stage_id, self.claim)
        self.assertFalse(no_email.collection_stage_id)
        self.assertEqual(in_legal.collection_pipeline_id, self.legal)
        self.assertIn('No Mail Co', result['params']['message'])
        self.assertIn('Court Co', result['params']['message'])

    def test_invalid_email_blocked_two_addresses_ok(self):
        bad = self.env['res.partner'].create({'name': 'Bad Mail Co', 'email': 'bad-mail.com'})
        two = self.env['res.partner'].create({'name': 'Two Mail Co', 'email': 'a@two.com   b@two.com'})
        self._invoice(two, 400.0, '2026-10-20')   # an open balance keeps it on the board
        wiz = self._wizard(bad | two, stage_id=self.claim.id)
        self.assertIn('not valid', wiz.preview_html)
        wiz.action_confirm()
        self.assertFalse(bad.collection_stage_id)
        self.assertEqual(two.collection_stage_id, self.claim)

    def test_ac15_record_without_email(self):
        no_email = self.env['res.partner'].create({'name': 'Phone Only'})
        self._invoice(no_email, 300.0, '2026-10-20')
        wiz = self._wizard(no_email, stage_id=self.reminder1.id, send_mode='record',
                           channel='call', note='Spoke with the owner')
        wiz.action_confirm()
        self.assertEqual(no_email.collection_stage_id, self.reminder1)
        note = self._notes(no_email, 'note_cat_stage_recorded')
        self.assertEqual(note.channel, 'call')
        self.assertIn('Phone call', note.body)
        self.assertIn('Spoke with the owner', note.body)

    # --- VIP approvals and credit hold -----------------------------------------
    def test_ac16_vip_credit_hold_via_approval(self):
        self.customer.category_id = [(4, self.vip_tag.id)]
        wiz = self._wizard(self.customer, stage_id=self.hold.id)
        sent_before = len(self.customer.message_ids)
        wiz.action_confirm()
        self.assertFalse(self.customer.collection_stage_id, "nothing moves before approval")
        self.assertEqual(len(self.customer.message_ids), sent_before, "nothing sent")
        request = self.env['collection.approval'].search([('partner_id', '=', self.customer.id)])
        self.assertEqual(request.state, 'pending')
        self.assertTrue(self.customer.collection_awaiting_approval)
        request.action_approve_owner()
        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.approved_as, 'owner')
        self.assertEqual(request.decided_by, self.env.user)
        self.assertEqual(self.customer.collection_stage_id, self.hold)
        self.assertAlmostEqual(self.customer.credit_limit, 1000.0)
        self.assertTrue(self.customer.use_partner_credit_limit)
        self.assertIn('Approved by owner', self._notes(self.customer, 'note_cat_email_sent').body)

    def test_approval_rights(self):
        user = self.env['res.users'].create({
            'name': 'Collector', 'login': 'collector_fu',
            'group_ids': [(6, 0, [self.env.ref('collections_workbench.group_collection_user').id])],
        })
        self.customer.category_id = [(4, self.vip_tag.id)]
        self._wizard(self.customer, stage_id=self.final.id).action_confirm()
        request = self.env['collection.approval'].search([('partner_id', '=', self.customer.id)])
        with self.assertRaises(AccessError):
            request.with_user(user).action_approve_manager()
        request.action_reject()
        self.assertEqual(request.state, 'rejected')
        self.assertFalse(self.customer.collection_stage_id)

    # --- events outside the stages ----------------------------------------------
    def test_ac17_statement_does_not_change_stage(self):
        self._wizard(self.customer, stage_id=self.claim.id).action_confirm()
        wiz = self._wizard(self.customer, kind='soa')
        self.assertIn('Statement of account', wiz.subject)
        wiz.action_confirm()
        self.assertEqual(self.customer.collection_stage_id, self.claim)
        self.assertEqual(len(self._notes(self.customer, 'note_cat_email_sent')), 2)
        statement = self.customer.message_ids.filtered(lambda m: m.subject == wiz.subject)
        self.assertTrue(statement.attachment_ids.filtered(lambda a: a.name.endswith('.pdf')),
                        "the statement PDF is attached")

    # --- automatic tags ---------------------------------------------------------
    def test_ac22_legal_case_adds_court_tag(self):
        wiz = self._wizard(self.customer, pipeline_id=self.legal.id)
        self.assertEqual(wiz.stage_id, self.legal.stage_ids[:1])
        wiz.write({'send_mode': 'record', 'channel': 'other'})
        wiz.action_confirm()
        court = self.env.ref('collections_workbench.tag_court_case')
        self.assertIn(court, self.customer.category_id)
        log = self._notes(self.customer, 'note_cat_system').filtered(lambda n: 'Court case' in n.body)
        self.assertIn(self.env.user.name, log.body)
        snap = self._snapshot()
        line = snap.line_ids.filtered(lambda l: l.partner_id == self.customer)
        self.assertEqual(line.section, 'court')

    def test_ac22_live_section_on_existing_snapshot(self):
        snap = self._snapshot()
        line = snap.line_ids.filtered(lambda l: l.partner_id == self.customer)
        self.assertEqual(line.live_section, 'active')
        self._wizard(self.customer, pipeline_id=self.legal.id, send_mode='record', channel='other').action_confirm()
        line.invalidate_recordset(['live_section'])
        self.assertEqual(line.live_section, 'court', "shows in Court case at once")
        self.assertEqual(line.section, 'active', "the frozen figure does not change")
        rows = self.env['collection.snapshot.line'].workbench_data(snap.id, [('live_section', '=', 'court')])['rows']
        self.assertEqual([r['partner_id'] for r in rows], [self.customer.id])

    def test_ac23_blacklist_recommended_note(self):
        self.env['collection.note'].create({
            'partner_id': self.customer.id,
            'category_id': self.env.ref('collections_workbench.note_cat_blacklist_rec').id,
            'body': 'Never pays',
        })
        self.assertIn(self.env.ref('collections_workbench.tag_blacklist'), self.customer.category_id)
        self.assertEqual(self.customer.collection_pipeline_id, self.blacklist)

    # --- payments ---------------------------------------------------------------
    def test_ac25_full_payment_closes_cycle(self):
        self._wizard(self.customer, stage_id=self.claim.id).action_confirm()
        self._pay(self.inv_acme, 1000.0, fields.Date.today())
        # no explicit recompute: matching the payment applies the rule at once
        self.assertFalse(self.customer.collection_stage_id)
        self.assertFalse(self.customer.collection_pipeline_id)
        cycle = self.customer.collection_cycle_ids
        self.assertEqual(len(cycle), 1)
        self.assertEqual(cycle.max_stage_id, self.claim)

    def test_partial_payment_pauses_escalation(self):
        self._wizard(self.customer, stage_id=self.reminder1.id).action_confirm()
        self._pay(self.inv_acme, 400.0, fields.Date.today())
        self.assertEqual(self.customer.collection_stage_id, self.partial)
        self.assertEqual(self.customer.collection_prev_stage_id, self.reminder1)
        self.assertEqual(self.customer.collection_next_action, 'Remaining balance request')
        self.assertFalse(self.customer.collection_due_to_send)
        # after the pause the remaining balance request is due
        later = fields.Date.today() + timedelta(days=8)
        self.customer._collection_recompute_status(today=later)
        self.assertTrue(self.customer.collection_due_to_send)
        self._wizard(self.customer, kind='remain').action_confirm()
        self.assertTrue(self.customer.collection_remain_sent)
        self.customer._collection_recompute_status()
        self.assertEqual(self.customer.collection_next_stage_id,
                         self.env.ref('collections_workbench.stage_reminder_2'))

    # --- suggestions --------------------------------------------------------------
    def test_next_stage_due_and_blacklist_suggestion(self):
        self._snapshot()
        # no explicit recompute: generation computes the statuses at once
        self.assertEqual(self.customer.collection_next_stage_id, self.claim, "eligible from day one")
        self.assertTrue(self.customer.collection_due_to_send)
        self._wizard(self.customer, stage_id=self.claim.id).action_confirm()
        self.assertEqual(self.customer.collection_next_stage_id, self.reminder1)
        self.assertFalse(self.customer.collection_due_to_send)
        self.customer._collection_recompute_status(today=fields.Date.today() + timedelta(days=7))
        self.assertTrue(self.customer.collection_due_to_send)
        # final notice expired with no payment: blacklist suggested (VR-13)
        self._wizard(self.customer, stage_id=self.final.id).action_confirm()
        self.customer._collection_recompute_status(today=fields.Date.today() + timedelta(days=10))
        self.assertTrue(self.customer.collection_suggest_blacklist)

    def test_ac20_ac21_payment_checks(self):
        snap = self._snapshot()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE collection_snapshot SET pull_date = pull_date - interval '1 day' WHERE id = %s",
            [snap.id])
        snap.invalidate_recordset(['pull_date'])
        self.env['collection.note'].create({
            'partner_id': self.customer.id, 'category_id': self.cat_paid_full.id,
            'body': 'Owner says paid'})
        line = snap.line_ids.filtered(lambda l: l.partner_id == self.customer)
        self.assertEqual(line.pay_check, 'missing')
        self._unreconciled_payment(self.customer, 1000.0, fields.Date.today())
        line.invalidate_recordset()
        self.assertEqual(line.pay_check, 'unrec')
        mismatches = self.env['collection.snapshot.line'].search(
            [('pay_check', 'in', ['unrec', 'missing', 'nonote'])])
        self.assertIn(line, mismatches)

    # --- board and guards ---------------------------------------------------------
    def test_board_drop(self):
        action = self.customer.collection_board_drop(self.claim.id)
        self.assertEqual(action['res_model'], 'collection.followup.wizard')
        self.assertFalse(self.customer.collection_stage_id, "no move before confirmation")
        mgmt_less = self.env['collection.stage'].create({
            'name': 'Called', 'pipeline_id': self.collection.id, 'sequence': 15})
        self.assertFalse(self.customer.collection_board_drop(mgmt_less.id))
        self.assertEqual(self.customer.collection_stage_id, mgmt_less)
        with self.assertRaises(UserError):
            self.customer.collection_stage_id = self.claim

    def test_ac18_customer_replied(self):
        snap = self._snapshot()
        self._wizard(self.customer, stage_id=self.claim.id).action_confirm()
        self.customer.message_post(body='We will pay Friday', message_type='email',
                                   author_id=self.customer.id, subject='Re: Account balance')
        line = snap.line_ids.filtered(lambda l: l.partner_id == self.customer)
        self.assertTrue(line.customer_replied)
        self.assertIn(self.env.user.partner_id, line.message_partner_ids)

    # --- simulation parity: thanks, quick filters, bulk assign ----------------
    def test_thanks_due_after_payment(self):
        self._snapshot()
        self._wizard(self.customer, stage_id=self.reminder1.id).action_confirm()
        self.assertFalse(self.customer.collection_thanks_due)
        self._pay(self.inv_acme, 400.0, fields.Date.today())
        self.assertTrue(self.customer.collection_thanks_due)
        Line = self.env['collection.snapshot.line']
        self.assertIn(self.customer, Line.search([('thanks_due', '=', True)]).partner_id)
        self._wizard(self.customer, kind='thanks').action_confirm()
        self.assertFalse(self.customer.collection_thanks_due)
        self.assertEqual(self.customer.collection_thanks_date, fields.Date.today())

    def test_new_quick_filters(self):
        Line = self.env['collection.snapshot.line']
        lines = Line.search([('snapshot_id', '=', self._snapshot().id)])
        self.assertEqual(set(Line.search([('stale', '=', True), ('id', 'in', lines.ids)]).partner_id.ids),
                         {self.customer.id, self.customer2.id}, "no notes yet: both stale")
        self.env['collection.note'].create({'partner_id': self.customer.id,
                                            'category_id': self.cat_no_answer.id})
        self.assertEqual(Line.search([('stale', '=', True), ('id', 'in', lines.ids)]).partner_id, self.customer2)
        self.customer.credit_limit = 500.0
        self.assertEqual(Line.search([('credit_state', '=', 'hold'), ('id', 'in', lines.ids)]).partner_id,
                         self.customer)
        self.assertEqual(Line.search([('credit_state', '=', 'none'), ('id', 'in', lines.ids)]).partner_id,
                         self.customer2)
        for domain in ([('suggest_blacklist', '=', True)], [('suggest_close', '=', True)],
                       [('activity_ids', '!=', False)], [('pattern', '=', 'chronic')],
                       [('live_section', 'in', ['active', 'court'])], [('deadline_state', '=', 'soon')]):
            Line.search(domain)
        # Odoo 19 hands boolean filters to search methods as 'in' / 'not in'
        agreement = self.env['res.partner.category'].create({'name': 'Agreement test'})
        self.env.company.collection_agreement_tag_ids = [(6, 0, agreement.ids)]
        self.customer.category_id = [(4, agreement.id)]
        self.assertEqual(Line.search([('is_agreement', '=', True), ('id', 'in', lines.ids)]).partner_id,
                         self.customer)
        self.assertEqual(Line.search([('is_agreement', '=', False), ('id', 'in', lines.ids)]).partner_id,
                         self.customer2)
        self.assertFalse(Line.search([('awaiting_approval', '=', True), ('id', 'in', lines.ids)]))

    def test_bulk_change_assignee(self):
        employee = self.env['hr.employee'].sudo().create({'name': 'Bulk Collector'})
        lines = self.env['collection.snapshot.line'].search([('snapshot_id', '=', self._snapshot().id)])
        wizard = self.env['collection.assign.wizard'].with_context(
            default_line_ids=lines.ids).create({'employee_id': employee.id})
        self.assertEqual(wizard.line_count, 2)
        wizard.action_confirm()
        self.assertEqual(self.customer.collection_assignee_id, employee)
        self.assertEqual(self.customer2.collection_assignee_id, employee)
