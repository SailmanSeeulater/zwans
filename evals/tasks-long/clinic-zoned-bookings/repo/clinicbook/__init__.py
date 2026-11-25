"""clinicbook: appointments for a group of clinics."""

from .clinic import ClinicBook
from .errors import (
    BackupError,
    BookingError,
    ClinicError,
    Conflict,
    ImportFailed,
    InvalidTime,
    NotFound,
    OutsideOpeningHours,
    StatusError,
    StorageError,
    ValidationError,
)
from .recurrence import Recurrence
from .storage import Store

__all__ = [
    "BackupError",
    "BookingError",
    "ClinicBook",
    "ClinicError",
    "Conflict",
    "ImportFailed",
    "InvalidTime",
    "NotFound",
    "OutsideOpeningHours",
    "Recurrence",
    "StatusError",
    "StorageError",
    "Store",
    "ValidationError",
]

__version__ = "1.6.2"
