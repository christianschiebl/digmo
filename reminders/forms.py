from django import forms

from .models import ReminderRule


class ReminderRuleForm(forms.ModelForm):
    """
    Formular für Reminder-Regeln pro Makler.
    Broker wird im View gesetzt, Trigger-Event ist im MVP immer DOCUMENT_SENT.
    """

    class Meta:
        model = ReminderRule
        fields = ["days_after", "brevo_template_id", "subject", "body", "enabled"]

    def clean(self):
        cleaned = super().clean()
        brevo_template_id = cleaned.get("brevo_template_id")
        subject = cleaned.get("subject")
        body = cleaned.get("body")

        if not brevo_template_id and not (subject and body):
            raise forms.ValidationError(
                "Entweder eine Brevo Template-ID angeben oder Subject und Body als Fallback ausfüllen."
            )

        return cleaned



