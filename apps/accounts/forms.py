from django import forms

from apps.accounts.models import Site, User


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ["name", "address"]


class UserInviteForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "role", "whatsapp_phone"]
