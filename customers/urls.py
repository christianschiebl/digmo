from django.urls import path

from .views import (
    CustomerCreateView,
    CustomerDetailView,
    CustomerInviteCreateView,
    CustomerListView,
    CustomerUpdateView,
    InviteAcceptView,
)

urlpatterns = [
    path("customers/", CustomerListView.as_view(), name="customer_list"),
    path("customers/create/", CustomerCreateView.as_view(), name="customer_create"),
    path("customers/<int:pk>/", CustomerDetailView.as_view(), name="customer_detail"),
    path(
        "customers/<int:pk>/edit/",
        CustomerUpdateView.as_view(),
        name="customer_update",
    ),
    path(
        "customers/<int:pk>/invite/",
        CustomerInviteCreateView.as_view(),
        name="customer_invite",
    ),
    path("invite/<str:token>/", InviteAcceptView.as_view(), name="customer_invite_accept"),
]


