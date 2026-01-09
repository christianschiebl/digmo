import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import CustomerProfileForm, CustomerSelfAssessmentForm, InvitePasswordForm
from .models import CustomerInvite, CustomerProfile
from documents.models import CustomerDocument


class BrokerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Stellt sicher, dass nur Makler (BROKER) Zugriff erhalten."""

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and getattr(user, "role", None) == user.Role.BROKER


class CustomerListView(BrokerRequiredMixin, ListView):
    model = CustomerProfile
    template_name = "customers/customer_list.html"
    context_object_name = "customers"

    def get_queryset(self):
        return (
            CustomerProfile.objects.filter(broker=self.request.user)
            .select_related("broker")
            .order_by("-updated_at")
        )


class CustomerCreateView(BrokerRequiredMixin, CreateView):
    model = CustomerProfile
    form_class = CustomerProfileForm
    template_name = "customers/customer_form.html"
    success_url = reverse_lazy("customer_list")

    def form_valid(self, form):
        form.instance.broker = self.request.user
        return super().form_valid(form)


class CustomerUpdateView(BrokerRequiredMixin, UpdateView):
    model = CustomerProfile
    form_class = CustomerProfileForm
    template_name = "customers/customer_form.html"
    success_url = reverse_lazy("customer_list")

    def get_queryset(self):
        return CustomerProfile.objects.filter(broker=self.request.user)


class CustomerDetailView(BrokerRequiredMixin, DetailView):
    model = CustomerProfile
    template_name = "customers/customer_detail.html"
    context_object_name = "customer"

    def get_queryset(self):
        return CustomerProfile.objects.filter(broker=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["active_tab"] = self.request.GET.get("tab", "overview")
        invites = self.object.invites.all()
        ctx["invites"] = invites
        active_invite = next((invite for invite in invites if invite.is_active), None)
        ctx["active_invite"] = active_invite
        if active_invite is not None:
            ctx["active_invite_url"] = self.request.build_absolute_uri(
                active_invite.get_absolute_url()
            )
        ctx["invite_expiry_days"] = 14
        ctx["documents"] = (
            CustomerDocument.objects.filter(
                customer=self.object, broker=self.request.user
            )
            .select_related("template")
            .order_by("-created_at")
        )
        return ctx


class CustomerInviteCreateView(BrokerRequiredMixin, View):
    """Broker erzeugt einen neuen Invite-Link für einen bestehenden Kunden."""

    def post(self, request, pk):
        customer = get_object_or_404(
            CustomerProfile, pk=pk, broker=request.user
        )
        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(days=14)
        CustomerInvite.objects.create(
            broker=request.user,
            customer=customer,
            token=token,
            expires_at=expires_at,
        )
        return redirect("customer_detail", pk=customer.pk)


class InviteAcceptView(View):
    """Endkunde öffnet Invite-Link, setzt Passwort und füllt Selbstauskunft aus."""

    template_name = "customers/invite_accept.html"

    def _get_invite(self, token: str) -> CustomerInvite:
        return get_object_or_404(CustomerInvite, token=token)

    def get(self, request, token: str):
        invite = self._get_invite(token)
        if not invite.is_active:
            return render(request, "customers/invite_invalid.html", {"invite": invite})

        password_form = InvitePasswordForm()
        profile_form = CustomerSelfAssessmentForm(instance=invite.customer)
        return render(
            request,
            self.template_name,
            {
                "invite": invite,
                "password_form": password_form,
                "profile_form": profile_form,
            },
        )

    def post(self, request, token: str):
        invite = self._get_invite(token)
        if not invite.is_active:
            return render(request, "customers/invite_invalid.html", {"invite": invite})

        password_form = InvitePasswordForm(request.POST)
        profile_form = CustomerSelfAssessmentForm(
            request.POST, instance=invite.customer
        )

        if password_form.is_valid() and profile_form.is_valid():
            customer_profile = profile_form.save()
            email = customer_profile.email
            User = get_user_model()

            if not email:
                password_form.add_error(
                    None, "Für dieses Profil ist keine E-Mail-Adresse hinterlegt."
                )
            else:
                # Existierenden CUSTOMER-Account verknüpfen oder neuen anlegen.
                user = customer_profile.user
                if user is None:
                    try:
                        user = User.objects.get(email=email, role=User.Role.CUSTOMER)
                    except User.DoesNotExist:
                        user = User.objects.create_user(
                            email=email,
                            password=password_form.cleaned_data["password1"],
                            role=User.Role.CUSTOMER,
                        )
                    else:
                        user.set_password(password_form.cleaned_data["password1"])
                        user.save()
                    customer_profile.user = user
                    customer_profile.save(update_fields=["user"])
                else:
                    user.set_password(password_form.cleaned_data["password1"])
                    user.save()

                invite.used_at = timezone.now()
                invite.save(update_fields=["used_at"])

                return render(
                    request,
                    "customers/invite_complete.html",
                    {"customer": customer_profile},
                )

        return render(
            request,
            self.template_name,
            {
                "invite": invite,
                "password_form": password_form,
                "profile_form": profile_form,
            },
        )


