from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import CustomerProfile


class CustomerProfileForm(forms.ModelForm):
    """Formular für Makler, um Kundenstammdaten zu pflegen."""

    class Meta:
        model = CustomerProfile
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "street",
            "postal_code",
            "city",
            "employment_status",
            "monthly_income",
            "status",
        ]


class CustomerSelfAssessmentForm(forms.ModelForm):
    """Formular für Endkunden-Selbstauskunft (Invite-Flow)."""

    class Meta:
        model = CustomerProfile
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "street",
            "postal_code",
            "city",
            "employment_status",
            "monthly_income",
        ]

    def save(self, commit=True):
        obj = super().save(commit=False)
        if obj.status == CustomerProfile.Status.NEW:
            obj.status = CustomerProfile.Status.IN_PROGRESS
        if commit:
            obj.save()
        return obj


class InvitePasswordForm(forms.Form):
    password1 = forms.CharField(
        label="Passwort",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Passwort bestätigen",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        if password:
            validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password1")
        p2 = cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Die Passwörter stimmen nicht überein.")
        return cleaned_data


