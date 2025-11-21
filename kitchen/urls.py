from django.urls import path
from . import views

urlpatterns = [
    path('', views.kitchen, name='kitchen'),
    path('toggle/<int:item_id>/', views.toggle_availability, name='toggle_availability'),
]