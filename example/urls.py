"""
URL configuration for example project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path

from example import views

urlpatterns = [
    path('admin/', admin.site.urls),
    # Demo views illustrating the sync vs async ORM paths against the test
    # LDAP directory. Run the example app under an ASGI server
    # (``uvicorn example.asgi:application``) for the async path to behave
    # as expected; ``runserver`` works too but is less representative.
    path('users/sync/', views.users_sync, name='users-sync'),
    path('users/async/', views.users_async, name='users-async'),
]
