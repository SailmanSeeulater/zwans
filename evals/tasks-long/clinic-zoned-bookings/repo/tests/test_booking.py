from datetime import date, datetime

import pytest
from clinicbook import (
    BookingError,
    Conflict,
    InvalidTime,
    NotFound,
    OutsideOpeningHours,
    StatusError,
    ValidationError,
)
from support import visit, wall


def test_a_booking_is_kept_with_its_times(book):
    appt = visit(book, datetime(2026, 1, 12, 9, 0), minutes=45, kind="review")

    assert appt.id == "A0001"
    assert wall(appt.start) == "2026-01-12 09:00"
    assert wall(appt.end) == "2026-01-12 09:45"
    assert book.appointment("A0001") is appt
    assert appt.status == "booked" and appt.kind == "review"


def test_a_start_can_be_given_as_text(book):
    appt = visit(book, "2026-01-12 10:15")

    assert wall(appt.start) == "2026-01-12 10:15"


def test_the_same_clinician_cannot_be_double_booked(book):
    first = visit(book, datetime(2026, 1, 12, 9, 0))

    with pytest.raises(Conflict) as caught:
        visit(book, datetime(2026, 1, 12, 9, 15), room="C2", patient="P0002")

    assert caught.value.clashes == [first]


def test_the_same_room_and_patient_cannot_be_double_booked(book):
    visit(book, datetime(2026, 1, 12, 9, 0))

    with pytest.raises(Conflict):
        visit(book, datetime(2026, 1, 12, 9, 0), clinician="dr-lind", patient="P0002")
    with pytest.raises(Conflict):
        visit(book, datetime(2026, 1, 12, 9, 20), clinician="dr-lind", room="C2")


def test_back_to_back_appointments_are_fine(book):
    visit(book, datetime(2026, 1, 12, 9, 0))
    visit(book, datetime(2026, 1, 12, 9, 30), patient="P0002")
    visit(book, datetime(2026, 1, 12, 8, 30), patient="P0003")

    assert len(book.appointments(clinic="camden")) == 3


def test_bookings_must_fit_the_opening_hours(book):
    with pytest.raises(OutsideOpeningHours):
        visit(book, datetime(2026, 1, 12, 7, 45))
    with pytest.raises(OutsideOpeningHours):
        visit(book, datetime(2026, 1, 12, 17, 45))  # runs past 18:00
    with pytest.raises(OutsideOpeningHours):
        visit(book, datetime(2026, 1, 14, 12, 15))  # Wednesday lunch break
    with pytest.raises(OutsideOpeningHours):
        visit(book, datetime(2026, 1, 11, 10, 0))  # Sunday

    assert wall(visit(book, datetime(2026, 1, 12, 17, 30)).end) == "2026-01-12 18:00"
    assert wall(visit(book, datetime(2026, 1, 10, 12, 30)).end) == "2026-01-10 13:00"


def test_closed_days_cannot_be_booked(book):
    book.close_day("camden", date(2026, 1, 16), "staff training")

    with pytest.raises(OutsideOpeningHours, match="staff training"):
        visit(book, datetime(2026, 1, 16, 10, 0))


def test_times_must_be_on_the_grid_and_not_in_the_past(book):
    with pytest.raises(InvalidTime):
        visit(book, datetime(2026, 1, 12, 9, 2))
    with pytest.raises(ValidationError):
        visit(book, datetime(2026, 1, 12, 9, 0), minutes=32)
    with pytest.raises(InvalidTime):
        visit(book, datetime(2026, 1, 2, 9, 0))


def test_clinicians_and_rooms_must_belong_to_the_clinic(book):
    book.add_clinic("islington", "Islington Clinic", zone="Europe/London")
    book.add_room("islington", "I1", "Room 1")

    with pytest.raises(BookingError):
        visit(book, datetime(2026, 1, 12, 9, 0), room="I1")
    with pytest.raises(BookingError):
        visit(book, datetime(2026, 1, 12, 9, 0), clinic="islington", room="I1")
    with pytest.raises(NotFound):
        visit(book, datetime(2026, 1, 12, 9, 0), patient="P0099")


def test_cancelling_frees_the_time(book):
    appt = visit(book, datetime(2026, 1, 12, 9, 0))
    book.cancel(appt.id, reason="patient called")

    other = visit(book, datetime(2026, 1, 12, 9, 0), patient="P0002")

    assert appt.status == "cancelled" and "patient called" in appt.notes
    assert other.status == "booked"
    with pytest.raises(StatusError):
        book.cancel(appt.id)


def test_rescheduling_moves_the_appointment_and_checks_again(book):
    appt = visit(book, datetime(2026, 1, 12, 9, 0))
    visit(book, datetime(2026, 1, 12, 11, 0), patient="P0002")

    book.reschedule(appt.id, start=datetime(2026, 1, 13, 14, 0), minutes=60)
    assert wall(appt.start) == "2026-01-13 14:00" and wall(appt.end) == "2026-01-13 15:00"

    with pytest.raises(Conflict):
        book.reschedule(appt.id, start=datetime(2026, 1, 12, 11, 15))
    assert wall(appt.start) == "2026-01-13 14:00"

    # moving onto its own old time is fine
    book.reschedule(appt.id, start=datetime(2026, 1, 13, 14, 30), minutes=30)
    assert wall(appt.end) == "2026-01-13 15:00"


def test_completed_and_no_show_appointments_are_final(book):
    a = visit(book, datetime(2026, 1, 12, 9, 0))
    b = visit(book, datetime(2026, 1, 12, 10, 0))
    book.complete(a.id)
    book.mark_no_show(b.id)

    with pytest.raises(StatusError):
        book.reschedule(a.id, start=datetime(2026, 1, 13, 9, 0))
    assert [x.status for x in book.appointments()] == ["completed", "no_show"]


def test_appointments_can_be_filtered(book):
    visit(book, datetime(2026, 1, 13, 9, 0))
    visit(book, datetime(2026, 1, 12, 9, 0), clinician="dr-lind", room="C2", patient="P0002")
    visit(book, datetime(2026, 1, 12, 11, 0), patient="P0003")

    assert [a.id for a in book.appointments()] == ["A0002", "A0003", "A0001"]
    assert [a.id for a in book.appointments(clinician="dr-osei")] == ["A0003", "A0001"]
    assert [a.id for a in book.appointments(patient="P0002")] == ["A0002"]


def test_setting_up_validates_input(book):
    with pytest.raises(ValidationError):
        book.add_clinic("Bad Id", "Somewhere", zone="Europe/London")
    with pytest.raises(ValidationError):
        book.add_clinic("leeds", "Leeds Clinic", zone="leeds")
    with pytest.raises(ValidationError):
        book.add_clinic("leeds", "Leeds Clinic", zone="Europe/London", hours={"mon": "18-08"})
    with pytest.raises(ValidationError):
        book.add_patient("Al", phone="call me")
    with pytest.raises(ValidationError):
        book.add_clinician("dr-x", "Dr X", clinics=[])


def test_patients_can_be_found_by_name_or_phone(book):
    assert [p.id for p in book.find_patients("jo")] == ["P0001"]
    assert [p.id for p in book.find_patients("07700 900003")] == ["P0003"]
    assert book.find_patients("nobody") == []
