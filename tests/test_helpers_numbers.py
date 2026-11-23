"""`holds_number`: a number is found where it stands alone, not inside a random id."""
import pytest

from helpers import count_number, holds_number, number_places


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


def test_the_count_is_of_the_places_where_it_stands_alone():
    assert count_number('{"pid": 260} x=260; 2600 260px', 260) == 2
    assert count_number("", 260) == 0


def test_a_number_added_in_one_place_and_removed_from_another_is_not_hidden_by_the_count():
    """185 BG: the same count, but the number now stands where it did not."""
    before = 'status 409; "code": 409'
    after = 'status 409; "pid": 409'
    assert count_number(after, 409) == count_number(before, 409)
    assert not number_places(after, 409) <= number_places(before, 409)
    assert number_places(before, 409) <= number_places(before, 409)
