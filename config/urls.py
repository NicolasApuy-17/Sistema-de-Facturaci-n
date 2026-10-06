from django.urls import include, path
from django.contrib.auth import views as auth

urlpatterns = [
    path('ingresar/', auth.LoginView.as_view(template_name='login.html'), name='login'),
    path('salir/', auth.LogoutView.as_view(), name='logout'),
    path('', include('core.urls')),
]
