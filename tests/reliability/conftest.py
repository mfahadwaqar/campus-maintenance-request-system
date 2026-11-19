import pytest

from reports.transitions import seed_allowed_transitions


@pytest.fixture(autouse=True)
def reseed_transition_rules(transactional_db):
    """Threaded tests commit for real, and the database is emptied after each one.

    The status rules are data (a table), so put them back before every reliability test.
    """
    seed_allowed_transitions()
