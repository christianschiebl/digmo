from django.urls import path

from .views import ReminderRuleCreateView, ReminderRuleListView, ReminderRuleUpdateView


urlpatterns = [
    path("reminders/", ReminderRuleListView.as_view(), name="reminderrule_list"),
    path(
        "reminders/rules/create/",
        ReminderRuleCreateView.as_view(),
        name="reminderrule_create",
    ),
    path(
        "reminders/rules/<int:pk>/edit/",
        ReminderRuleUpdateView.as_view(),
        name="reminderrule_update",
    ),
]



