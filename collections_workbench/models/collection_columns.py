"""Column definitions of the Collections table, shared by the OWL table and
the Excel export so both have the same layout and colours (Appendix D)."""

SECTIONS = [
    # key, label, header colour (Excel + table)
    ('customer', 'Customer', '#E8EEF7'),
    ('periods', 'Periods', '#FFF4DB'),
    ('total', 'Total', '#E3F1E6'),
    ('reconciliation', 'Reconciliation', '#FBE3E1'),
    ('live', 'Live comparison', '#E6F2F8'),
    ('notes', 'Notes', '#F0E9F7'),
    ('credit', 'Credit limit', '#F2F2F2'),
]

# key, label, section, type, default visible, locked (FR-7), filter, domain field
COLUMNS = [
    ('partner', 'Customer', 'customer', 'text', True, True, 'pick', 'partner_id'),
    ('salesman', 'Salesperson', 'customer', 'm2o', True, False, 'pick', 'salesman_id'),
    ('assignee', 'Assigned to', 'customer', 'm2o', True, False, 'pick', 'assignee_id'),
    ('tags', 'Tags', 'customer', 'tags', False, False, 'pick', 'partner_id.category_id'),
    ('pipeline', 'Pipeline', 'customer', 'char', False, False, 'pick', 'pipeline_id.name'),
    ('total_due', 'Total due', 'total', 'money', True, True, 'range', 'total_due'),
    ('unreconciled_now', 'Unreconciled', 'reconciliation', 'money', True, False, 'range', 'unreconciled_now'),
    ('soa_balance', 'SOA balance', 'reconciliation', 'money', True, False, 'range', 'soa_balance'),
    ('live_balance', 'Updated balance', 'live', 'money', False, False, 'range', 'live_balance'),
    ('live_collected', 'Collected', 'live', 'money', False, False, 'range', 'live_collected'),
    ('live_status', 'Status', 'live', 'selection', False, False, 'pick', 'live_status'),
    ('pay_check', 'Payment check', 'live', 'selection', False, False, 'pick', 'pay_check'),
    ('changed_invoice_count', 'Changed after snapshot', 'live', 'int', False, False, None, None),
    ('note', 'Latest note', 'notes', 'note', True, True, 'pick', 'latest_note_category_id'),
    ('stage', 'Stage', 'notes', 'char', True, False, 'pick', 'stage_id.name'),
    ('next_action', 'Suggested', 'notes', 'char', False, False, None, None),
    ('pattern_label', 'Pattern', 'notes', 'char', False, False, 'pick', 'pattern'),
    ('deadline_label', 'Deadline', 'notes', 'char', False, False, 'pick', 'deadline_state'),
    ('credit_limit', 'Credit limit', 'credit', 'money', False, False, 'range', 'credit_limit'),
]

STATUS_LABELS = {'paid': 'Paid', 'partly': 'Partly paid', 'none': 'Not paid'}
PAY_CHECK_LABELS = {
    'ok': 'Payment confirmed',
    'unrec': 'New unreconciled payment',
    'missing': 'No trace of payment, check the bank',
    'nonote': 'Payment without a note',
}


def columns_for_client():
    return {
        'sections': [{'key': k, 'label': l, 'color': c} for k, l, c in SECTIONS],
        'columns': [{
            'key': key, 'label': label, 'section': section, 'type': ctype, 'visible': visible,
            'locked': locked, 'filter': filt, 'field': field,
        } for key, label, section, ctype, visible, locked, filt, field in COLUMNS],
        'status_labels': STATUS_LABELS,
        'pay_check_labels': PAY_CHECK_LABELS,
    }
