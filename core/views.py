from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.views.generic import TemplateView

from customers.models import CustomerProfile
from documents.models import CustomerDocument


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "home.html"

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        role = getattr(user, "role", None)
        if role == user.Role.CUSTOMER:
            return redirect("customer_dashboard")
        if role != user.Role.BROKER:
            return HttpResponseForbidden("Dieses Dashboard ist nur für Makler verfügbar.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        broker = self.request.user
        ctx["customer_total"] = CustomerProfile.objects.filter(broker=broker).count()
        # Alle nicht abgeschlossenen Dokumente (Entwurf oder versendet) für diesen Makler
        ctx["open_documents_total"] = (
            CustomerDocument.objects.filter(broker=broker)
            .exclude(status=CustomerDocument.Status.COMPLETED)
            .count()
        )
        return ctx


class CustomerDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "customer_dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated or getattr(user, "role", None) != user.Role.CUSTOMER:
            return HttpResponseForbidden("Dieses Dashboard ist nur für Endkunden verfügbar.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        profile = getattr(user, "customer_profile", None)
        ctx["profile"] = profile
        if profile is not None:
            ctx["documents"] = (
                CustomerDocument.objects.filter(customer=profile, broker=profile.broker)
                .select_related("template")
                .order_by("-created_at")
            )
        else:
            ctx["documents"] = CustomerDocument.objects.none()
        return ctx

