from app import domain

BASE = {"TO": "Bangalore", "ShipmentDate": "2026-10-20T00:00:00"}


def row(**kw):
    return {**BASE, **kw}


def test_assigned_and_loading():
    assert domain.derive_status(row(DOAllocatedDate="2026-10-19T19:09:00"))[0] == "assigned"
    assert domain.derive_status(row(PlantEntrydate="2026-10-19T22:17:00"))[0] == "loading"


def test_dispatched_from_plant_exit_or_gate():
    assert domain.derive_status(row(PlantExitDate="2026-10-20T10:37:00"))[0] == "dispatched"
    assert domain.derive_status(row(PlantExitDate="2026-10-20T03:07:00", JSWLeft="2026-10-20T03:53:59"))[0] == "dispatched"


def test_tumkur_is_transit_for_bangalore_but_near_for_tumkur():
    assert domain.derive_status(row(JSWLeft="x", TMKEntry="2026-10-20T11:44:46"))[0] == "in_transit"
    assert domain.derive_status(row(TO="Tumkur", TMKEntry="2026-10-20T11:13:59"))[0] == "near_destination"


def test_arrived_and_delivered():
    assert domain.derive_status(row(TO="Tumkur", unloadLocReachedTime="2026-10-20T09:28:22"))[0] == "arrived"
    status, at, inferred = domain.derive_status(row(unloadedTime="2026-10-19T12:29:36", BLRLeft="2026-10-19T13:39:05"))
    assert (status, inferred) == ("delivered", False)
    assert at.isoformat() == "2026-10-19T06:59:36+00:00"  # IST -> UTC


def test_return_leg_without_unload_stamp_counts_as_delivered():
    status, at, inferred = domain.derive_status(row(unloadLocReachedTime="2026-10-19T02:00:00",
                                                    TMKReEntry="2026-10-20T05:34:38"))
    assert status == "delivered" and inferred is True


def test_epoch_placeholder_is_ignored():
    assert domain.parse_ts("1970-01-01T05:30:00") is None
    assert domain.parse_position({"lat": "15.19", "lng": "76.64", "TimeStamp": "1970-01-01T05:30:00"}) is None
    assert domain.parse_position({"lat": None, "lng": None, "TimeStamp": "2026-10-20T12:00:00"}) is None
    pos = domain.parse_position({"lat": "15.1004619598389", "lng": "76.877082824707", "Heading": 335,
                                 "TimeStamp": "2026-10-20T12:19:33"})
    assert pos and pos["lat"] == 15.100462 and pos["heading"] == 335


def test_phone_cleaning():
    assert domain.clean_phones("1234567890") == []
    assert domain.clean_phones("000") == []
    assert domain.clean_phones("0000000000") == []
    assert domain.clean_phones("  8904944871") == ["8904944871"]
    assert domain.clean_phones("7406299506, 8217396535") == ["7406299506", "8217396535"]
    assert domain.clean_phones("9798312377 / 8757070643") == ["9798312377", "8757070643"]
    assert domain.clean_phones("9844585599/7892321078") == ["9844585599", "7892321078"]


def test_names_and_plates():
    assert domain.clean_driver_name("DHIRENDRA KUMAR  YADAV-7662") == "Dhirendra Kumar Yadav"
    assert domain.clean_driver_name("UMESH RAY -5136") == "Umesh Ray"
    assert domain.format_plate("KA 06 AB 6272") == "KA 06 AB 6272"
    assert domain.format_plate("KA06AC0271") == "KA 06 AC 0271"
    assert domain.norm_party("INTERNATIONAL TUBES INDIA PVT. LTD") == domain.norm_party("International Tubes India Pvt Ltd")


def test_timeline_tumkur_has_no_city_step():
    fields = {"DOAllocatedDate": "2026-10-19T16:52:00", "PlantEntrydate": "2026-10-19T19:19:00",
              "PlantExitDate": "2026-10-19T23:32:00", "JSWLeft": "2026-10-20T00:11:53",
              "TMKEntry": "2026-10-20T08:33:21", "unloadLocReachedTime": "2026-10-20T09:28:22"}
    tl = domain.build_timeline(fields, "Tumkur", "arrived", False, None)
    assert [t["key"] for t in tl] == ["assigned", "loading", "dispatched", "hub", "arrived", "delivered"]
    assert [t["state"] for t in tl][-2:] == ["current", "pending"]


def test_timeline_inferred_delivery_note():
    tl = domain.build_timeline({"JSWLeft": "2026-10-18T03:21:23"}, "Bangalore", "delivered", True,
                               domain.parse_ts("2026-10-19T13:39:05"))
    last = tl[-1]
    assert last["state"] == "done" and last["note"] and last["at"] == "2026-10-19T08:09:05Z"
