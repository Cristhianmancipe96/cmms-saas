"""Render a bound field with the ARIA wiring a Django widget doesn't add.

`{{ form.as_p }}` — what the earlier briefs use — emits the input and the
error text as unrelated siblings: nothing tells assistive technology that
the red sentence below the box explains *that* box, and nothing marks the
box as invalid. These screens are the first ones a técnico fills in with
gloves on a phone, so the pairing is done properly here.
"""

from django import template

register = template.Library()


@register.filter
def control(field):
    """The widget itself, described by its help text and its errors."""
    described_by = []
    if field.help_text:
        described_by.append(f"{field.auto_id}_help")
    if field.errors:
        described_by.append(f"{field.auto_id}_error")

    attrs = {}
    if described_by:
        attrs["aria-describedby"] = " ".join(described_by)
    if field.errors:
        attrs["aria-invalid"] = "true"
    return field.as_widget(attrs=attrs)
