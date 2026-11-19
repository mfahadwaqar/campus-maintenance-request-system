import re

from django.core.exceptions import ValidationError

from .models import RoomLocation


DORM_FLOORS = {
    "A": 4, "B": 4, "C": 4, "D": 4, "F": 4, "G": 4, "H": 4,
    "E": 3, "J": 3, "K": 3,
    "L": 4, "M": 4, "N": 4, "P3": 4, "Q": 4, "R": 4, "S": 4,
    "T": 4, "U": 4, "V": 4, "W": 4, "X": 4, "Y": 4,
}


def validate_room_location(building, value):
    """Validate dorm room templates and provisional SV{NN}{UNIT}{ROOM} entries."""
    if not building.is_active:
        raise ValidationError("Choose an active building.")
    room_code = value.strip().upper()
    village = re.fullmatch(r"SV(?P<number>\d{2})(?P<unit>[A-Z])(?P<room>\d{1,2})", room_code)
    if village:
        number = int(village.group("number"))
        match = re.search(
            r"(?:SV|STUDENT VILLAGE\s+)(\d{1,2})$",
            building.name.upper(),
        )
        if not 1 <= number <= 70 or match is None or int(match.group(1)) != number:
            raise ValidationError("The Student Village room code must match the selected building.")
        return room_code

    location = RoomLocation.objects.filter(
        code=room_code,
        location_type=RoomLocation.LocationType.DORMITORY,
        is_active=True,
    ).first()
    if location is None or location.name != building.name:
        raise ValidationError("Choose a valid room for the selected dormitory.")

    dorm = location.name.removeprefix("Dormitory ")
    floors = DORM_FLOORS.get(dorm)
    room_match = re.fullmatch(
        rf"{re.escape(dorm)}(?P<floor>[1-4])(?P<room>\d{{2}})",
        room_code,
    )
    if (
        floors is None
        or room_match is None
        or int(room_match.group("floor")) > floors
        or not 1 <= int(room_match.group("room")) <= 10
    ):
        raise ValidationError("Dorm rooms must match the selected dorm, floor, and room template.")
    return room_code
