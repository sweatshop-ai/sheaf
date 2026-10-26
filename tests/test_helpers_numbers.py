"""`holds_number`: a number is found where it stands alone, not inside a random id."""
import pytest

from helpers import holds_number


@pytest.mark.parametrize("text, found", [
    ('"boot": "fc3e9c10-cb0c-443a-94a1-c8cd260c38c4"', False),   # digits inside a uuid
    ('"id": "c8cd260"', False),
    ("port 2600", False),
    ("width: 260px", False),
    ("v1.260", False),
    ("260.5", False),
    ('{"pid": 260}', True),
    ("x=260;", True),
    ("260", True),
])
def test_a_number_is_found_only_where_it_stands_alone(text, found):
    assert holds_number(text, 260) is found
