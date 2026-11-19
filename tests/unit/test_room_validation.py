"""Unit tests for room validation (white-box: branches and boundary values).

Rule under test (accounts/room_validation.py):
- Dorm rooms are {DORM}{FLOOR}{ROOM}. Four-floor dorms take floors 1 to 4, three-floor
  dorms (E, J, K) take floors 1 to 3, and rooms run 01 to 10.
- Student village rooms are SV{NN}{UNIT}{ROOM}; NN must be 1 to 70 and match the building.
"""

import pytest
from django.core.exceptions import ValidationError

from accounts.models import Building, RoomLocation
from accounts.room_validation import validate_room_location

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]


def dorm_building(letter):
    building, _ = Building.objects.get_or_create(
        name=f"Dormitory {letter}", defaults={"zone": "Zone 1"}
    )
    return building


def seed_room(building, code):
    RoomLocation.objects.get_or_create(
        code=code,
        defaults={
            "name": building.name,
            "location_type": RoomLocation.LocationType.DORMITORY,
        },
    )


# (dorm letter, code typed, expected valid)  -- boundaries of floor and room number
DORM_CASES = [
    ("A", "A101", True),   # first valid room on the first floor
    ("A", "A110", True),   # upper room boundary
    ("A", "A111", False),  # just past the upper room boundary
    ("A", "A100", False),  # just below the lower room boundary
    ("A", "A401", True),   # top floor of a four-floor dorm
    ("A", "A501", False),  # one floor too high
    ("A", "A001", False),  # floor zero
    ("E", "E301", True),   # top floor of a three-floor dorm
    ("E", "E401", False),  # a three-floor dorm has no floor 4
    ("A", "B101", False),  # room belongs to another dorm
    ("A", "A1", False),    # too short
    ("A", "", False),      # empty
]


@pytest.mark.parametrize("letter,code,expected", DORM_CASES)
@pytest.mark.django_db
def test_dorm_room_boundaries(letter, code, expected):
    building = dorm_building(letter)
    if expected:
        seed_room(building, code)

    if expected:
        assert validate_room_location(building, code) == code
    else:
        with pytest.raises(ValidationError):
            validate_room_location(building, code)


@pytest.mark.django_db
def test_room_code_is_normalised_before_checking():
    building = dorm_building("A")
    seed_room(building, "A101")

    assert validate_room_location(building, "  a101 ") == "A101"


@pytest.mark.django_db
def test_inactive_building_is_refused_with_its_own_message():
    building = dorm_building("A")
    building.is_active = False
    building.save()

    with pytest.raises(ValidationError, match="active building"):
        validate_room_location(building, "A101")


@pytest.mark.django_db
def test_a_room_of_another_building_names_the_dorm_in_the_message():
    building = dorm_building("B")
    seed_room(dorm_building("A"), "A101")

    with pytest.raises(ValidationError, match="valid room"):
        validate_room_location(building, "A101")


# (village number, code, expected valid)
VILLAGE_CASES = [
    (1, "SV01A1", True),    # lowest village number
    (70, "SV70B10", True),  # highest village number, two-digit room
    (4, "sv04a1", True),    # lower case is normalised
    (0, "SV00A1", False),   # below the range
    (71, "SV71A1", False),  # above the range
    (5, "SV04A1", False),   # code does not match the selected building
    (4, "SV04A100", False), # room number has three digits
]


@pytest.mark.parametrize("number,code,expected", VILLAGE_CASES)
@pytest.mark.django_db
def test_student_village_code_boundaries(number, code, expected):
    building = Building.objects.create(name=f"SV{number}", zone="Village")

    if expected:
        assert validate_room_location(building, code) == code.strip().upper()
    else:
        with pytest.raises(ValidationError):
            validate_room_location(building, code)
