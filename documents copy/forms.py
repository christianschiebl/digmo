from django import forms
from django.core.exceptions import ValidationError

from .models import CustomerDocument, DocumentTemplate


class DocumentTemplateForm(forms.ModelForm):
    class Meta:
        model = DocumentTemplate
        fields = ["name", "type", "file", "field_schema"]


class CustomerDocumentForm(forms.ModelForm):
    """Formular für Makler zum Anlegen eines Kundendokuments."""

    class Meta:
        model = CustomerDocument
        fields = ["template", "uploaded_file", "status"]


class CustomerSelfUploadDocumentForm(forms.ModelForm):
    """
    Stark reduziertes Formular für Endkunden:
    - nur Datei-Upload, Status/Template werden vom System gesetzt.
    """

    class Meta:
        model = CustomerDocument
        fields = ["uploaded_file"]


class AutofillForm(forms.Form):
    """
    Formular für den Broker:
    - Entweder ein Template wählen (neues Dokument erzeugen)
    - oder ein bestehendes Kundendokument neu befüllen.
    """

    template = forms.ModelChoiceField(
        label="Template",
        queryset=DocumentTemplate.objects.none(),
        required=False,
        help_text="Wählen Sie ein Template, um ein neues Dokument für den Kunden zu erzeugen.",
    )
    document = forms.ModelChoiceField(
        label="Bestehendes Kundendokument",
        queryset=CustomerDocument.objects.none(),
        required=False,
        help_text="Alternativ: vorhandenes Dokument mit Kundendaten neu befüllen.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Labels für Auswahllisten: Dateinamen anzeigen
        self.fields["template"].label_from_instance = (
            lambda obj: obj.filename or obj.name
        )
        self.fields["document"].label_from_instance = (
            lambda obj: obj.filename or f"Dokument #{obj.pk}"
        )

    def clean(self):
        cleaned = super().clean()
        template = cleaned.get("template")
        document = cleaned.get("document")

        # genau eine Option muss gewählt sein
        if bool(template) == bool(document):
            raise ValidationError(
                "Wählen Sie entweder ein Template oder ein bestehendes Dokument – aber nicht beides."
            )

        return cleaned

