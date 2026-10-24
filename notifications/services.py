import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse

from accounts.models import User
from .models import Notification


logger = logging.getLogger(__name__)


def queue_report_notifications(report, *, event: str, recipients) -> None:
    """Persist privacy-limited notifications and send their emails after commit."""

    notification_ids = []
    for user in recipients:
        if not user.is_active:
            continue
        notification = Notification.objects.create(
            user=user,
            report=report,
            message=f"Request #{report.pk} {event}.",
            channel=Notification.Channel.EMAIL,
        )
        notification_ids.append(notification.pk)

    if notification_ids:
        transaction.on_commit(
            lambda ids=tuple(notification_ids): send_queued_notifications(ids)
        )


def _report_url_name(user: User) -> str:
    if user.role == User.Role.OFFICER:
        return "accounts:officer_report_detail"
    if user.role == User.Role.TECHNICIAN:
        return "assignments:technician_report_detail"
    return "reports:detail"


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
            notification.save(update_fields=("status",))
            continue

        path = reverse(
            _report_url_name(recipient),
            args=(notification.report_id,),
        )
        link = f"{settings.SITE_BASE_URL}{path}"
        body = f"{notification.message} View the request: {link}"
        try:
            send_mail(
                subject="Maintenance request update",
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception("Failed to send notification %s.", notification.pk)
            notification.status = Notification.Status.FAILED
        else:
            notification.status = Notification.Status.SENT
        notification.save(update_fields=("status",))
