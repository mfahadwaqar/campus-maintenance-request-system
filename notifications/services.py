import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import Notification

logger = logging.getLogger(__name__)


def queue_report_notifications(report, *, event: str, recipients, lead: str = "") -> None:
    """Persist privacy-limited notifications and send their emails after commit."""

    notification_ids = []
    for user in recipients:
        if not user.is_active:
            continue
        notification = Notification.objects.create(
            user=user,
            report=report,
            message=(
                f"{lead} {report.ticket_no} {event}."
                if lead
                else f"{report.ticket_no}: {event}."
            ),
            channel=Notification.Channel.EMAIL,
        )
        notification_ids.append(notification.pk)

    if notification_ids:
        transaction.on_commit(
            lambda ids=tuple(notification_ids): send_queued_notifications(ids)
        )


def send_queued_notifications(notification_ids) -> None:
    """Send ticket-only email, recording delivery failures without raising."""

    notifications = Notification.objects.filter(pk__in=notification_ids).select_related(
        "user"
    )
    for notification in notifications:
        recipient = notification.user
        if not recipient.email:
            logger.warning(
                "Cannot send notification %s because its recipient has no email.",
                notification.pk,
            )
            notification.status = Notification.Status.FAILED
            notification.delivery_status = Notification.Status.FAILED
            notification.save(update_fields=("status", "delivery_status"))
            continue
        try:
            send_mail(
                subject="Maintenance request update",
                message=notification.message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception("Failed to send notification %s.", notification.pk)
            notification.status = Notification.Status.FAILED
            notification.delivery_status = Notification.Status.FAILED
        else:
            notification.status = Notification.Status.SENT
            notification.delivery_status = Notification.Status.SENT
            notification.sent_at = timezone.now()
        notification.save(update_fields=("status", "delivery_status", "sent_at"))
