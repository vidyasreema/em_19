"""Helpers for search methods of non-stored fields.

Odoo 19 hands boolean filters to search methods already normalised:
('field', '=', True) arrives as ('field', 'in', {True}) and
('field', '=', False) as ('field', 'not in', {True})."""


def bool_search_positive(operator, value):
    """True if the filter asks for records where the field is set,
    False if it asks for records where it is not, None if it matches all
    (the caller then returns an empty domain)."""
    if operator in ('in', 'not in'):
        wanted = {bool(v) for v in value}
        if operator == 'not in':
            wanted = {True, False} - wanted
    elif operator in ('=', '!='):
        wanted = {bool(value)} if operator == '=' else {not bool(value)}
    else:
        raise ValueError("Unsupported operator %r on a boolean filter" % operator)
    if not wanted:
        raise ValueError("Empty boolean filter")
    if len(wanted) == 2:
        return None
    return wanted.pop()
