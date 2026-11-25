"""Background jobs, run every few minutes by cron (`clinicbook jobs run`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .booking import BookingService
from .notify import Notifier
from .reminders import ReminderPlanner
from .repository import Repository
from .storage import Store
from .waitlist import Waitlist
from .webhooks import WebhookDispatcher


@dataclass
class JobReport:
    reminders_sent: list[str] = field(default_factory=list)
    no_shows: list[str] = field(default_factory=list)
    webhooks_delivered: int = 0
    waitlist_booked: list[str] = field(default_factory=list)
    waitlist_expired: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"reminders sent: {len(self.reminders_sent)}",
            f"no-shows marked: {len(self.no_shows)}",
            f"webhooks delivered: {self.webhooks_delivered}",
            f"waitlist booked: {len(self.waitlist_booked)}",
            f"waitlist expired: {len(self.waitlist_expired)}",
        ]


class Jobs:
    def __init__(
        self,
        store: Store,
        repo: Repository,
        booking: BookingService,
        planner: ReminderPlanner,
        notifier: Notifier,
        webhooks: WebhookDispatcher,
        waitlist: Waitlist,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.repo = repo
        self.booking = booking
        self.planner = planner
        self.notifier = notifier
        self.webhooks = webhooks
        self.waitlist = waitlist
        self.clock = clock

    def send_reminders(self, now: datetime) -> list[str]:
        sent = []
        for reminder in self.planner.due(now):
            appt = self.repo.appointment(reminder.appointment)
            self.notifier.send("reminder", appt)
            self.planner.mark_sent(reminder, now)
            sent.append(reminder.id)
        return sent

    def mark_no_shows(self, now: datetime) -> list[str]:
        grace = timedelta(minutes=self.store.settings.no_show_grace)
        marked = []
        for appt in self.repo.appointments(status="booked"):
            if appt.end + grace <= now:
                self.booking.mark_no_show(appt.id)
                marked.append(appt.id)
        return marked

    def run(self, now: datetime | None = None) -> JobReport:
        now = now or self.clock()
        report = JobReport()
        report.reminders_sent = self.send_reminders(now)
        report.no_shows = self.mark_no_shows(now)
        report.webhooks_delivered = self.webhooks.retry(now)
        report.waitlist_expired = [w.id for w in self.waitlist.expire(now)]
        report.waitlist_booked = [a.id for a in self.waitlist.offer(now)]
        return report
