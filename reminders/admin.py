from django.contrib import admin

from .models import ReminderLog, ReminderRule


@admin.register(ReminderRule)
class ReminderRuleAdmin(admin.ModelAdmin):
    list_display = (
        "broker",
        "trigger_event",
        "days_after",
        "enabled",
        "brevo_template_id",
        "created_at",
    )
    list_filter = ("trigger_event", "enabled", "broker")
    search_fields = ("broker__email", "brevo_template_id", "subject")


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = (
        "broker",
        "customer",
        "document",
        "rule",
        "due_at",
        "sent_at",
        "status",
        "provider_response_id",
    )
    list_filter = ("status", "broker")
    search_fields = (
        "customer__first_name",
        "customer__last_name",
        "customer__email",
    )
    readonly_fields = (
        "due_at",
        "sent_at",
        "status",
        "provider_response_id",
        "error_text",
        "created_at",
    )



