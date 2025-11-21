from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.customer_dashboard, name='customer_dashboard'),
    path('product/<str:product_type>/<int:product_id>/', views.product_view, name='product_view'),
    path('order/', views.place_order, name='place_order'),
    path('pay/', views.pay, name='pay'),
    path('clear-orders/', views.clear_orders, name='clear_orders'), 
    path('place_order/', views.place_order, name='place_order'),
    path('delete-item/<str:uuid>/', views.delete_cart_item, name='delete_cart_item'),
    path('confirm-pay/', views.bill_view, name='confirm_pay'),
    path('confirm-cash/', views.confirm_cash, name='confirm_cash'),
    path('cancel_order/', views.cancel_order, name='cancel_order'),
    path('complete_order/', views.confirm_pay, name='confirm_payment'),
    path('if-ready/', views.if_ready, name='if_ready'),
    path('Cassa-Cassandra/', views.logo, name='logo'),
]