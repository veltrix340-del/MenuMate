from django.contrib import admin
from .models import MenuItem, Order, OrderItem, Payment, Charges, Employee
# Register your models here.

admin.site.register(MenuItem)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(Payment)
admin.site.register(Charges)
admin.site.register(Employee)


