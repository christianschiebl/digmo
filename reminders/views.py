from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import CreateView, ListView, UpdateView

from .forms import ReminderRuleForm
from .models import ReminderLog, ReminderRule


class BrokerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Stellt sicher, dass nur Makler (BROKER) Zugriff erhalten."""

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and getattr(user, "role", None) == user.Role.BROKER


class ReminderRuleListView(BrokerRequiredMixin, ListView):
    model = ReminderRule
    template_name = "reminders/reminder_rule_list.html"
    context_object_name = "rules"

    def get_queryset(self):
        return ReminderRule.objects.filter(broker=self.request.user).order_by("days_after")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["logs"] = (
            ReminderLog.objects.filter(broker=self.request.user)
            .select_related("customer", "document", "rule")
            .order_by("-due_at")[:20]
        )
        return ctx


class ReminderRuleCreateView(BrokerRequiredMixin, CreateView):
    model = ReminderRule
    form_class = ReminderRuleForm
    template_name = "reminders/reminder_rule_form.html"

    def form_valid(self, form):
        form.instance.broker = self.request.user
        # Trigger-Event ist im MVP immer DOCUMENT_SENT.
        form.instance.trigger_event = ReminderRule.TriggerEvent.DOCUMENT_SENT
        return super().form_valid(form)

    def get_success_url(self):
        # Zurück zur Übersicht aller Regeln
        from django.urls import reverse_lazy

        return reverse_lazy("reminderrule_list")


class ReminderRuleUpdateView(BrokerRequiredMixin, UpdateView):
    model = ReminderRule
    form_class = ReminderRuleForm
    template_name = "reminders/reminder_rule_form.html"

    def get_queryset(self):
        # Nur Reminder-Regeln des aktuellen Brokers
        return ReminderRule.objects.filter(broker=self.request.user)

    def get_success_url(self):
        from django.urls import reverse_lazy

        return reverse_lazy("reminderrule_list")



