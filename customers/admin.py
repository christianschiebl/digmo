from django.contrib import admin

from .models import CustomerInvite, CustomerProfile


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "last_name",
        "first_name",
        "email",
        "broker",
        "status",
        "updated_at",
    )
    list_filter = ("status", "broker")
    search_fields = ("first_name", "last_name", "email")


@admin.register(CustomerInvite)
class CustomerInviteAdmin(admin.ModelAdmin):
    list_display = ("customer", "broker", "token", "expires_at", "used_at")
    list_filter = ("broker",)
    search_fields = (
        "token",
        "customer__first_name",
        "customer__last_name",
        "customer__email",
    )


