"""Choosing who receives a document.

There is no free-text address field anywhere in this product, and that is a
security decision rather than a convenience one: a typed recipient is an
exfiltration channel — one letter changed in a domain and an audit report
leaves the company. The operator picks from the people who already have an
account in their own company, and the queryset that renders the checkboxes is
the same queryset that validates the submission.
"""

from django import forms

from apps.accounts.models import User


def recipient_queryset(company):
    """Active colleagues who have somewhere to receive mail."""
    if company is None:
        return User.objects.none()
    return (
        User.objects.filter(company=company, is_active=True)
        .exclude(email="")
        .order_by("first_name", "last_name", "username")
    )


class RecipientChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj: User) -> str:
        name = obj.get_full_name() or obj.get_username()
        return f"{name} · {obj.email}"


class RecipientsForm(forms.Form):
    recipients = RecipientChoiceField(
        label="Enviar a",
        queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={
            "required": "Elige al menos una persona.",
            "invalid_choice": "Esa persona no pertenece a tu empresa.",
            "invalid_pk_value": "Esa persona no pertenece a tu empresa.",
        },
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Bound at construction from the *acting user's* company, so a pk from
        # another tenant posted by hand is an invalid choice, not a send.
        self.fields["recipients"].queryset = recipient_queryset(company)
