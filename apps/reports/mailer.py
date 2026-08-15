"""Sending mail, and writing down what happened.

Two rules shape this module:

- **A dead SMTP server is not a 500.** `deliver` never raises: it returns a
  result per recipient, and the caller turns that into a Spanish message. An
  outage in a third-party mail relay must not take a maintenance screen with
  it.
- **Sending and logging are separate steps.** `deliver` talks to SMTP and
  writes nothing; `log` writes the row. They are split because one caller —
  the user invitation — rolls its database transaction back when delivery
  fails, and the row recording that failure has to survive that rollback.
"""

from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMessage

from apps.reports.models import NotificationLog

# Long enough for an SMTP traceback to be diagnosable, short enough that a
# chatty server cannot fill the table with one row.
MAX_ERROR_DETAIL = 500


@dataclass(frozen=True)
class Delivery:
    """What happened when we tried one address."""

    recipient: str
    subject: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def deliver(
    *,
    recipient: str,
    subject: str,
    body: str,
    attachment: tuple[str, bytes, str] | None = None,
) -> Delivery:
    """Send one message to one address. Never raises."""
    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    if attachment is not None:
        message.attach(*attachment)
    try:
        message.send(fail_silently=False)
    except Exception as error:  # SMTP, DNS, socket, TLS — all the same to the user
        return Delivery(recipient=recipient, subject=subject, error=str(error)[:MAX_ERROR_DETAIL])
    return Delivery(recipient=recipient, subject=subject)


def log(
    delivery: Delivery,
    *,
    company,
    kind: str,
    sent_by=None,
    asset=None,
    work_order=None,
) -> NotificationLog:
    """Record one attempt — successful or not."""
    return NotificationLog.objects.create(
        company=company,
        channel=NotificationLog.Channel.EMAIL,
        kind=kind,
        recipient=delivery.recipient,
        subject=delivery.subject,
        asset=asset,
        work_order=work_order,
        status=(
            NotificationLog.Status.SENT if delivery.ok else NotificationLog.Status.FAILED
        ),
        error_detail=delivery.error,
        sent_by=sent_by,
    )


def deliver_and_log(
    *,
    recipients,
    subject: str,
    body: str,
    attachment: tuple[str, bytes, str] | None = None,
    company,
    kind: str,
    sent_by=None,
    asset=None,
    work_order=None,
) -> list[Delivery]:
    """One message per address, one log row per address.

    One message each rather than a single mail with everyone in `To:`, so the
    supervisor's address is not disclosed to the technicians and one bad
    address cannot take the whole send down with it.
    """
    deliveries = []
    for recipient in recipients:
        delivery = deliver(
            recipient=recipient, subject=subject, body=body, attachment=attachment
        )
        log(
            delivery,
            company=company,
            kind=kind,
            sent_by=sent_by,
            asset=asset,
            work_order=work_order,
        )
        deliveries.append(delivery)
    return deliveries
