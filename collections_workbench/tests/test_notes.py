from datetime import date
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CollectionsCommon


@tagged('post_install', '-at_install')
class TestNotes(CollectionsCommon):

    def _note(self, cat, partner=None, **vals):
        return self.env['collection.note'].create({
            'partner_id': (partner or self.customer).id, 'category_id': cat.id, **vals})

    def test_ac10_promise_without_date_refused(self):
        with self.assertRaises(ValidationError):
            self._note(self.cat_promise, amount=100.0)

    def test_promise_without_amount_refused(self):
        with self.assertRaises(ValidationError):
            self._note(self.cat_promise, promise_date=fields.Date.add(fields.Date.today(), days=3))

    def test_promise_in_past_refused(self):
        with self.assertRaises(ValidationError):
            self._note(self.cat_promise, amount=100.0,
                       promise_date=fields.Date.subtract(fields.Date.today(), days=1))

    def test_ac11_note_cannot_be_edited_or_deleted(self):
        note = self._note(self.cat_contacted, body="Called")
        with self.assertRaises(UserError):
            note.body = "Changed"
        with self.assertRaises(UserError):
            note.unlink()

    def test_system_category_not_selectable(self):
        with self.assertRaises(UserError):
            self._note(self.env.ref('collections_workbench.note_cat_email_sent'))

    def _promise_on(self, day, promise_day, amount):
        with patch.object(fields.Date, 'context_today', return_value=day):
            return self._note(self.cat_promise, amount=amount, promise_date=promise_day)

    def test_ac12_promise_kept_and_broken(self):
        inv = self._invoice(self.customer, 2000.0, '2026-10-01')
        note = self._promise_on(date(2026, 11, 5), date(2026, 11, 10), 1000.0)
        # pending before date + grace (3 days)
        self.assertEqual(note._promise_state(date(2026, 11, 12)), 'pending')
        # nothing paid -> broken; pattern "Late once"
        self.assertEqual(note._promise_state(date(2026, 11, 14)), 'broken')
        self.assertEqual(self.customer._collection_pattern(date(2026, 11, 14)), 'once')
        # less than 50% paid is still broken
        self._pay(inv, 400.0, '2026-11-11')
        self.assertEqual(note._promise_state(date(2026, 11, 14)), 'broken')
        # reaching 50% by date + grace -> kept, pattern reliable
        self._pay(inv, 100.0, '2026-11-13')
        self.assertEqual(note._promise_state(date(2026, 11, 14)), 'kept')
        self.assertEqual(self.customer._collection_pattern(date(2026, 11, 14)), 'reliable')

    def test_pattern_repeat_and_unreachable(self):
        self._invoice(self.customer, 2000.0, '2026-10-01')
        self._promise_on(date(2026, 10, 1), date(2026, 10, 5), 500.0)
        self._promise_on(date(2026, 10, 10), date(2026, 10, 12), 500.0)
        self.assertEqual(self.customer._collection_pattern(date(2026, 11, 1)), 'repeat')
        with patch.object(fields.Date, 'context_today', return_value=date(2026, 11, 1)):
            self._note(self.cat_no_answer)
            self._note(self.cat_no_answer)
        self.assertEqual(self.customer._collection_pattern(date(2026, 11, 1)), 'unreach')

    def test_deadline_states(self):
        self._invoice(self.customer, 2000.0, '2026-10-01')
        self._promise_on(date(2026, 11, 1), date(2026, 11, 10), 500.0)
        c = self.customer
        self.assertEqual(c._collection_deadline(date(2026, 11, 1))[0], 'open')
        self.assertEqual(c._collection_deadline(date(2026, 11, 5))[0], 'soon')
        self.assertEqual(c._collection_deadline(date(2026, 11, 10))[0], 'today')
        self.assertEqual(c._collection_deadline(date(2026, 11, 11))[0], 'late')
        with patch.object(fields.Date, 'context_today', return_value=date(2026, 11, 11)):
            self._note(self.cat_paid_full)
        self.assertEqual(c._collection_deadline(date(2026, 11, 11))[0], 'closed')

    def test_field_visit_late_on_us(self):
        visit = self.env.ref('collections_workbench.note_cat_field_visit')
        with patch.object(fields.Date, 'context_today', return_value=date(2026, 11, 1)):
            self._note(visit, promise_date=date(2026, 11, 3))
        self.assertEqual(self.customer._collection_deadline(date(2026, 11, 4))[0], 'late_us')
