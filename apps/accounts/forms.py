from django import forms

from apps.accounts.models import Site, User


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ["name", "address"]


class UserInviteForm(forms.ModelForm):
    # User.role is blank=True at the model level so platform admins can carry
    # role="" — but an invited company user must always get one, otherwise
    # role_required silently denies them everywhere with no way to self-fix.
    role = forms.ChoiceField(choices=User.Role.choices, label="Rol")

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "role", "whatsapp_phone"]
