"""Test URLs."""

from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import include, path

urlpatterns = [
    path('admin/login/', LoginView.as_view(template_name='registration/login.html')),
    path('admin/', admin.site.urls),
    path('inbox/notifications/', include('notifications.urls', namespace='notifications')),
]
