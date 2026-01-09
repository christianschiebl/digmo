from django.contrib import admin

from .models import CustomerDocument, DocumentTemplate


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "broker", "created_at")
    list_filter = ("type", "broker")
    search_fields = ("name",)


@admin.register(CustomerDocument)
class CustomerDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "customer",
        "broker",
        "template",
        "status",
        "created_at",
        "sent_to_customer_at",
    )
    list_filter = ("status", "broker")
    search_fields = ("customer__first_name", "customer__last_name", "customer__email")


