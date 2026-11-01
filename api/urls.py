from django.urls import path

from .views import FindRouteView

urlpatterns = [
    path('find-route/', FindRouteView.as_view(), name='find-route'),
]
