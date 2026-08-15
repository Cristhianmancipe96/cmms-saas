"""Spanish subject lines and bodies. Plain text on purpose.

An HTML mail is a second design system to keep in sync, and the payload here is
the attachment — the body only has to say what arrived, from whom, and about
which machine.
"""

from django.template.loader import render_to_string


def _message(template: str, context: dict) -> str:
    # `.strip()` because a template that ends with a newline before `{% endblock %}`
    # otherwise sends a mail that opens with a blank line.
    return render_to_string(template, context).strip()


def asset_record_message(*, asset, sender) -> tuple[str, str]:
    subject = f"Hoja de vida · {asset.code} — {asset.name}"
    body = _message(
        "reports/email/asset_record.txt",
        {"asset": asset, "sender": sender, "company": asset.company},
    )
    return subject, body


def work_order_report_message(*, work_order, sender) -> tuple[str, str]:
    subject = f"Informe de OT #{work_order.pk} · {work_order.asset.code}"
    body = _message(
        "reports/email/work_order_report.txt",
        {"wo": work_order, "sender": sender, "company": work_order.company},
    )
    return subject, body


def temp_password_message(*, user, temp_password, company, login_url) -> tuple[str, str]:
    subject = f"Tu acceso a Vectron Management · {company.name}"
    body = _message(
        "reports/email/temp_password.txt",
        {
            "user": user,
            "temp_password": temp_password,
            "company": company,
            "login_url": login_url,
        },
    )
    return subject, body
