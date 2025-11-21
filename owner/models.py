from django.db import models
from datetime import date

class MenuItem(models.Model):
    AVAILABLE = 1
    OUT_OF_STOCK = 0
    DELETE_CHOICES = ((AVAILABLE, 'AVAILABLE'), (OUT_OF_STOCK, 'OUT OF STOCK'))
    
    CATEGORY_CHOICES = [
        ('Bites', 'Bites'),
        ('Brews', 'Brews'),
    ]

    name = models.CharField(max_length=100)
    price = models.FloatField()
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    image = models.ImageField(upload_to='images/')
    delete_status = models.IntegerField(choices=DELETE_CHOICES, default=AVAILABLE)

    def __str__(self):
        return self.name

class Order(models.Model):
    STATUS_CHOICES = [
        ('Accept', 'Accept'),
        ('Ready', 'Ready'),
        ('Delivered', 'Delivered'),
    ]
    session_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Accept')
    table_number = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    removed = models.BooleanField(default=False)
    is_notified = models.BooleanField(default=False)

    def __str__(self):
        return f"Order #{self.table_number} at {self.created_at}"

    def subtotal(self):
        return sum(item.total for item in self.items.all())


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    total = models.FloatField(default=0.0)

    def save(self, *args, **kwargs):
        self.total = round(self.item.price * self.quantity, 2)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item.name} x {self.quantity}"


class Charges(models.Model):
    tax = models.FloatField()
    service_charge = models.FloatField()
    
    def __str__(self):
        return f"Tax: {self.tax}%, Service Charge: {self.service_charge}%"


class Payment(models.Model):
    CASH = 1
    ONLINE = 0
    PAYMENT_METHOD = (
        (CASH, 'Cash'),
        (ONLINE, 'Online'),
    )

    order = models.ForeignKey('Order', on_delete=models.CASCADE)
    table_number = models.PositiveIntegerField()
    session_id = models.CharField(max_length=100, null=True, blank=True)
    subtotal = models.FloatField()
    tax = models.FloatField(null=True, blank=True)
    service_charge = models.FloatField(null=True, blank=True)
    total = models.FloatField(null=True, blank=True)
    bill_number = models.CharField(max_length=50)
    bill_date = models.CharField(max_length=20)
    bill_time = models.CharField(max_length=20)
    payment_method = models.IntegerField(choices=PAYMENT_METHOD, null=True, blank=True)
    feedback = models.TextField(null=True, blank=True)
    rating = models.IntegerField(null=True, blank=True) 
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    notified = models.BooleanField(default=False)
    is_paid = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Calculate tax and service charge automatically if not already set
        if self.tax is None or self.service_charge is None or self.total is None:
            charges = Charges.objects.first()
            if charges:
                self.tax = round(self.subtotal * (charges.tax / 100), 2)
                self.service_charge = round(self.subtotal * (charges.service_charge / 100), 2)
                self.total = round(self.subtotal + self.tax + self.service_charge, 2)
            else:
                self.tax = 0
                self.service_charge = 0
                self.total = self.subtotal
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Bill {self.bill_number} - Table {self.table_number} - Amount: {self.total}"


class Employee(models.Model):
    STAFF_CHOICES = [
        ('Dining', 'Dining'),
        ('Kitchen', 'Kitchen'),
    ]

    EMPLOYMENT_TYPE_CHOICES = [
        ('Full-Time', 'Full-Time'),
        ('Part-Time', 'Part-Time'),
    ]

    name = models.CharField(max_length=100, null=False, blank=False)
    emp_image = models.ImageField(upload_to='images/',null=True)
    date_of_birth = models.DateField(null=False, blank=False)
    phno = models.CharField(max_length=10, null=True, blank=False)
    staff = models.CharField(max_length=10, choices=STAFF_CHOICES, null=False, blank=False)
    employment_type = models.CharField(max_length=10, choices=EMPLOYMENT_TYPE_CHOICES, null=False, blank=False)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.get_staff_display()})"

    class Meta:
        ordering = ['staff', 'name']

