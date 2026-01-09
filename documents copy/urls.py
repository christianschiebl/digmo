from django.urls import path

from .views import (
    CustomerDocumentCreateView,
    CustomerDocumentDeleteView,
    CustomerDocumentSelfDeleteView,
    CustomerDocumentSelfUploadView,
    CustomerDocumentUpdateView,
    CustomerAutofillView,
    DocumentTemplateCreateView,
    DocumentTemplateDeleteView,
    DocumentTemplateListView,
    DocumentTemplateUpdateView,
)

urlpatterns = [
    path(
        "documents/templates/",
        DocumentTemplateListView.as_view(),
        name="documenttemplate_list",
    ),
    path(
        "documents/templates/create/",
        DocumentTemplateCreateView.as_view(),
        name="documenttemplate_create",
    ),
    path(
        "documents/templates/<int:pk>/edit/",
        DocumentTemplateUpdateView.as_view(),
        name="documenttemplate_update",
    ),
    path(
        "documents/templates/<int:pk>/delete/",
        DocumentTemplateDeleteView.as_view(),
        name="documenttemplate_delete",
    ),
    path(
        "customers/<int:customer_pk>/documents/add/",
        CustomerDocumentCreateView.as_view(),
        name="customer_document_add",
    ),
    path(
        "customers/<int:customer_pk>/autofill/",
        CustomerAutofillView.as_view(),
        name="customer_autofill",
    ),
    path(
        "documents/<int:pk>/edit/",
        CustomerDocumentUpdateView.as_view(),
        name="customer_document_edit",
    ),
    path(
        "customer/documents/add/",
        CustomerDocumentSelfUploadView.as_view(),
        name="customer_document_self_add",
    ),
    path(
        "documents/<int:pk>/delete/",
        CustomerDocumentDeleteView.as_view(),
        name="customer_document_delete",
    ),
    path(
        "customer/documents/<int:pk>/delete/",
        CustomerDocumentSelfDeleteView.as_view(),
        name="customer_document_self_delete",
    ),
]


