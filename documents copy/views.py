from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, FormView, ListView, UpdateView

from customers.models import CustomerProfile

from .forms import (
    AutofillForm,
    CustomerDocumentForm,
    CustomerSelfUploadDocumentForm,
    DocumentTemplateForm,
)
from .models import CustomerDocument, DocumentTemplate
from .autofill import (
    run_autofill_for_customer,
    run_autofill_for_document,
    update_field_schema_for_template,
)


class BrokerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and getattr(user, "role", None) == user.Role.BROKER


class DocumentTemplateListView(BrokerRequiredMixin, ListView):
    model = DocumentTemplate
    template_name = "documents/template_list.html"
    context_object_name = "templates"

    def get_queryset(self):
        return DocumentTemplate.objects.filter(broker=self.request.user).order_by("name")


class DocumentTemplateCreateView(BrokerRequiredMixin, CreateView):
    model = DocumentTemplate
    form_class = DocumentTemplateForm
    template_name = "documents/template_form.html"
    success_url = reverse_lazy("documenttemplate_list")

    def form_valid(self, form):
        form.instance.broker = self.request.user
        response = super().form_valid(form)
        update_field_schema_for_template(self.object)
        return response


class DocumentTemplateUpdateView(BrokerRequiredMixin, UpdateView):
    model = DocumentTemplate
    form_class = DocumentTemplateForm
    template_name = "documents/template_form.html"
    success_url = reverse_lazy("documenttemplate_list")

    def get_queryset(self):
        return DocumentTemplate.objects.filter(broker=self.request.user)

    def form_valid(self, form):
        response = super().form_valid(form)
        update_field_schema_for_template(self.object)
        return response


class DocumentTemplateDeleteView(BrokerRequiredMixin, DeleteView):
    """Löschen eines Dokument-Templates durch den Makler."""

    model = DocumentTemplate
    template_name = "documents/template_confirm_delete.html"
    success_url = reverse_lazy("documenttemplate_list")

    def get_queryset(self):
        # Nur Templates des aktuellen Brokers dürfen gelöscht werden.
        return DocumentTemplate.objects.filter(broker=self.request.user)


class CustomerDocumentCreateView(BrokerRequiredMixin, CreateView):
    """Dokument-Upload & Zuordnung durch den Makler am Kundenprofil."""

    model = CustomerDocument
    form_class = CustomerDocumentForm
    template_name = "documents/customer_document_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(
            CustomerProfile, pk=self.kwargs["customer_pk"], broker=request.user
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Beim Upload soll kein Template mehr gewählt werden können.
        form.fields.pop("template", None)
        return form

    def form_valid(self, form):
        form.instance.broker = self.request.user
        form.instance.customer = self.customer
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("customer_detail", kwargs={"pk": self.customer.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["customer"] = self.customer
        return ctx


class CustomerDocumentUpdateView(BrokerRequiredMixin, UpdateView):
    """Status/Zuordnung für bestehendes Kundendokument bearbeiten."""

    model = CustomerDocument
    form_class = CustomerDocumentForm
    template_name = "documents/customer_document_form.html"

    def get_queryset(self):
        # Nur Dokumente des aktuellen Brokers dürfen bearbeitet werden.
        return CustomerDocument.objects.filter(broker=self.request.user).select_related(
            "customer"
        )

    def get_success_url(self):
        return reverse_lazy(
            "customer_detail", kwargs={"pk": self.object.customer.pk}
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Template-Zuordnung soll bei bestehenden Dokumenten nicht mehr änderbar sein.
        form.fields.pop("template", None)
        return form

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["customer"] = self.object.customer
        return ctx


class CustomerDocumentSelfUploadView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """
    Upload eines Dokuments direkt durch den Endkunden im Kundenportal.
    Das Dokument wird automatisch dem zugehörigen CustomerProfile + Broker zugeordnet.
    """

    model = CustomerDocument
    form_class = CustomerSelfUploadDocumentForm
    template_name = "documents/customer_self_document_form.html"
    success_url = reverse_lazy("customer_dashboard")

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and getattr(user, "role", None) == user.Role.CUSTOMER

    def dispatch(self, request, *args, **kwargs):
        self.profile = getattr(request.user, "customer_profile", None)
        if self.profile is None:
            # Kein Profil vorhanden → Upload nicht möglich
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.customer = self.profile
        form.instance.broker = self.profile.broker
        # Vom Kunden hochgeladene Dokumente starten als Entwurf
        if not form.instance.status:
            form.instance.status = CustomerDocument.Status.DRAFT
        return super().form_valid(form)


class CustomerDocumentDeleteView(BrokerRequiredMixin, DeleteView):
    """Löschen eines Kundendokuments durch den Makler."""

    model = CustomerDocument
    template_name = "documents/customer_document_confirm_delete.html"

    def get_queryset(self):
        return CustomerDocument.objects.filter(broker=self.request.user).select_related(
            "customer"
        )

    def get_success_url(self):
        return reverse_lazy(
            "customer_detail", kwargs={"pk": self.object.customer.pk}
        )


class CustomerDocumentSelfDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """Löschen eines eigenen Dokuments durch den Endkunden."""

    model = CustomerDocument
    template_name = "documents/customer_document_confirm_delete.html"
    success_url = reverse_lazy("customer_dashboard")

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and getattr(user, "role", None) == user.Role.CUSTOMER

    def get_queryset(self):
        profile = getattr(self.request.user, "customer_profile", None)
        if profile is None:
            return CustomerDocument.objects.none()
        return CustomerDocument.objects.filter(customer=profile, broker=profile.broker)


class CustomerAutofillView(BrokerRequiredMixin, FormView):
    """
    View für Flow C:
    1) Broker wählt Template für einen Kunden,
    2) Autofill erzeugt ein generiertes Dokument (DOCX/PDF),
    3) CustomerDocument wird gespeichert.
    """

    form_class = AutofillForm
    template_name = "documents/customer_autofill_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(
            CustomerProfile, pk=self.kwargs["customer_pk"], broker=request.user
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["template"].queryset = DocumentTemplate.objects.filter(
            broker=self.request.user
        )
        form.fields["document"].queryset = CustomerDocument.objects.filter(
            broker=self.request.user, customer=self.customer
        )
        return form

    def form_valid(self, form):
        template: DocumentTemplate = form.cleaned_data.get("template")
        document: CustomerDocument = form.cleaned_data.get("document")

        if template is not None:
            # Neues Dokument aus Template erzeugen
            run_autofill_for_customer(template, self.customer)
        else:
            # Beliebiges Kundendokument (mit oder ohne Template) neu mit Kundendaten befüllen
            run_autofill_for_document(document, self.customer)

        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("customer_detail", kwargs={"pk": self.customer.pk}) + "?tab=documents"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["customer"] = self.customer
        return ctx

