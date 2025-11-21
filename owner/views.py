from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from .models import MenuItem, Order, OrderItem, Payment, Charges, Employee
from django.contrib import messages
from collections import defaultdict
from .utils import generate_upi_qr
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from datetime import datetime
from django.http import JsonResponse
from django.urls import reverse
from .forms import TableUserForm
from django.contrib.auth.models import User, Group
from .forms import TablePasswordResetForm
from datetime import timedelta
from django.contrib.sessions.models import Session
from django.db.models import Count, Sum, Q



@never_cache
def table_login(request):
    # 🔒 If user is already logged in, redirect away
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('admin_dashboard')
        elif request.user.groups.filter(name='Kitchen').exists():
            return redirect('kitchen')
        else:
            return redirect('customer_dashboard')
    # Normal login process
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Redirect based on role
            if user.is_superuser:
                return redirect('admin_dashboard')
            elif user.groups.filter(name='Kitchen').exists():
                return redirect('kitchen')
            else:
                return redirect('logo')
        else:
            messages.error(request, 'Invalid login credentials')
    return render(request, 'login_table.html')

@login_required
@require_http_methods(["POST"])
def secure_logout(request):
    password = request.POST.get('password')
    user = request.user
    # Re-authenticate the user to verify password
    authenticated_user = authenticate(username=user.username, password=password)
    if authenticated_user is not None:
        logout(request)
        messages.success(request, 'You have been logged out.')
        return redirect('table_login')  # Or wherever you want to send them
    else:
        messages.error(request, 'Incorrect password. Logout cancelled.')
        return redirect('customer_dashboard')
    

def secure_admin_logout(request):
    if request.method == "POST":
        import json
        data = json.loads(request.body)
        password = data.get("password")

        # Validate password of current admin
        user = request.user
        if user.is_authenticated and user.check_password(password):
            logout(request)
            return JsonResponse({"success": True, "redirect_url": "/"})
        else:
            return JsonResponse({"success": False})
    return JsonResponse({"success": False}, status=400)


def admin_dashboard(request):
    category = request.GET.get('category', 'all')
    search_query = request.POST.get('q', '').strip()
    staff_filter = request.GET.get('staff', 'all') 
    categories = MenuItem.objects.values_list('category', flat=True).distinct()

    if category == 'all':
        items = MenuItem.objects.all()
    elif category == 'bites':
        items = MenuItem.objects.filter(category='Bites')
    elif category == 'brews':
        items = MenuItem.objects.filter(category='Brews')
    else:
        items = MenuItem.objects.none()

    request.session['category'] = category

    # Apply search filter if q exists
    if search_query:
        items = items.filter(name__icontains=search_query)

    orders = Order.objects.filter(removed=False).prefetch_related('items__item').order_by('-created_at')
    total_orders = Order.objects.count()

    payments = Payment.objects.select_related('order').order_by('-created_at')[:10]


    # Calculate today's revenue using subtotal()
    today = timezone.now().date()
    payments_today = Payment.objects.filter(
    created_at__date=today,
    is_paid=True
    )

    # Calculate total revenue from delivered orders today
    revenue = payments_today.aggregate(total=Sum('total'))['total'] or 0.0

    feedbacks = Payment.objects.filter(feedback__isnull=False).order_by('-created_at')

    # 📝 Charges handling
    charges = Charges.objects.first()

    if request.method == 'POST' and 'update_charges' in request.POST:
        tax = float(request.POST.get('tax', 0))
        service_charge = float(request.POST.get('service_charge', 0))

        if charges:
            charges.tax = tax
            charges.service_charge = service_charge
            charges.save()
            messages.success(request, "Charges updated successfully.")
        else:
            Charges.objects.create(
                tax=tax,
                service_charge=service_charge
            )
            messages.success(request, "Charges created successfully.")
        
        return redirect(f"{reverse('admin_dashboard')}?page=settings&set_sub=charge")

    
    page = request.GET.get('page')
    request.session['page'] = page

    set_sub = request.GET.get('set_sub')
    if set_sub:
        request.session["last_set_sub"] = set_sub
    else:
        set_sub = request.session.get("last_set_sub", "table") 

    # Tables (customers or table logins)
    tables = User.objects.filter(is_staff=False, is_superuser=False)

    # Groups (staff groups, e.g., kitchen, waiters)
    groups = Group.objects.all()

    # Find all active user IDs from sessions
    active_user_ids = []
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        data = session.get_decoded()
        uid = data.get('_auth_user_id')
        if uid:
            active_user_ids.append(int(uid))

    # Table Data
    table_data = []
    for t in tables:
        if t.id in active_user_ids:
            status = "active"   # Logged in right now
        elif t.last_login:
            status = "inactive" # Has logged in before, but not now
        else:
            status = "never"    # Never logged in
        
        table_data.append({
            "id": t.id,
            "username": t.username,
            "date_joined": t.date_joined,
            "last_login": t.last_login,
            "status": status,
        })

    # Group Data
    group_data = []
    for g in groups:
        group_data.append({
            "id": g.id,
            "name": g.name,
            "user_count": g.user_set.count(),
            "users": list(g.user_set.values("id", "username", "last_login")),
        })

    employees = Employee.objects.all()

    request.session['staff'] = staff_filter

    if staff_filter == "Dining":
        employees = employees.filter(staff="Dining", is_active=True)
    elif staff_filter == "Kitchen":
        employees = employees.filter(staff="Kitchen", is_active=True)
    elif staff_filter == "Full-Time":
        employees = employees.filter(employment_type="Full-Time", is_active=True)
    elif staff_filter == "Part-Time":
        employees = employees.filter(employment_type="Part-Time", is_active=True)
    elif staff_filter == "Removed":
        employees = employees.filter(is_active=False)
    else:
        employees = employees.filter(is_active=True)

    today = timezone.now().date()
    
    # --- Overview stats ---
    today_orders = Order.objects.filter(created_at__date=today)

    # Total customers today
    customers_today = today_orders.count()

    # Most ordered item today
    most_ordered_item_qs = OrderItem.objects.filter(order__created_at__date=today)\
        .values('item__name')\
        .annotate(quantity_sum=Sum('quantity'))\
        .order_by('-quantity_sum')
    most_ordered_item = most_ordered_item_qs[0]['item__name'] if most_ordered_item_qs else "N/A"

    # Revenue today
    revenue_today = Payment.objects.filter(created_at__date=today, is_paid=True).aggregate(total=Sum('total'))['total'] or 0.0

    # Average order value today
    avg_order_value = round(revenue_today / today_orders.count(), 2) if today_orders.exists() else 0.0


    total_orders = orders.count()
    accepted_count = orders.filter(status='Accept').count()
    ready_count = orders.filter(status='Ready').count()
    delivered_count = orders.filter(status='Delivered').count()
    pending_orders = orders.filter(status__in=['Accept', 'Ready']).count()
    cash_payments = Payment.objects.filter(payment_method=Payment.CASH, is_paid=True).count()
    online_payments = Payment.objects.filter(payment_method=Payment.ONLINE, is_paid=True).count()
    pending_payments = Payment.objects.filter(is_paid=False).count()
    active_tables = len([t for t in table_data if t['status'] == 'active'])
    inactive_tables = len([t for t in table_data if t['status'] != 'active'])


    return render(request, 'admin.html', {
        'menu_items': items,
        'categories': categories,
        'current_category': category,
        'orders': orders,
        'payments': payments,
        'total_orders': total_orders,
        'q': search_query,
        'revenue': revenue,
        'charges': charges,
        'payments_today': feedbacks,
        'stars': range(1, 6),
        'tables': table_data,
        'groups': group_data,
        'set_sub': set_sub,
        'employees': employees,
        'current_staff': staff_filter,
        'customers_today': customers_today,
        'most_ordered_item': most_ordered_item,
        'revenue_today': revenue_today,
        'avg_order_value': avg_order_value,
        'accepted_count': accepted_count,
        'ready_count': ready_count,
        'delivered_count': delivered_count,
        'pending_orders': pending_orders,
        'cash_payments': cash_payments,
        'online_payments': online_payments,
        'pending_payments': pending_payments,
        'active_tables': active_tables,
        'inactive_tables': inactive_tables,
    })

def toggle_employee_status(request, emp_id):
    employee = get_object_or_404(Employee, id=emp_id)
    employee.is_active = not employee.is_active
    if not employee.is_active:
        employee.left_at = timezone.now()
    else:
        employee.left_at = None
    employee.save()
    staff_filter = request.session.get('staff')
    status = "restored" if employee.is_active else "removed"
    messages.success(request, f"Employee {employee.name} has been {status}.")
    
    return redirect(f"{reverse('admin_dashboard')}?page=staff&staff={staff_filter}")


def add_menu_item(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        category = request.POST.get('category')
        price = request.POST.get('price')
        image = request.FILES.get('image')
        delete_status = request.POST.get('delete_status', 1)
        MenuItem.objects.create(
            name=name,
            category=category,
            price=price,
            image=image,
            delete_status=delete_status
        )
        return redirect(f"{reverse('admin_dashboard')}?page=menu")
    return render(request, 'admin.html')


def edit_menu_item(request):
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        item = get_object_or_404(MenuItem, id=item_id)
        item.name = request.POST.get('name')
        item.category = request.POST.get('category')
        item.price = request.POST.get('price')
        item.delete_status = request.POST.get('delete_status')
        if 'image' in request.FILES:
            item.image = request.FILES['image']
        item.save()
        return redirect(f"{reverse('admin_dashboard')}?page=menu")
    return render(request, 'admin.html')


def delete_menu_item(request, item_id):
    if request.method == 'POST':
        item = get_object_or_404(MenuItem, id=item_id)
        item.delete()  # Completely removes from database
        return redirect(f"{reverse('admin_dashboard')}?page=menu")
    return render(request, 'admin.html')


def free_table(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    order.removed = True
    order.save()
    return redirect(f"{reverse('admin_dashboard')}?page=orders")


def check_payment_status(request):
    # Get all payments that haven't been notified yet
    payments = Payment.objects.filter(is_paid=True , notified=False)
    data = []
    for payment in payments:
        data.append({
            'id': payment.id,
            'table_number': payment.table_number,
            'method': 'online' if payment.payment_method == Payment.ONLINE else 'cash',
            'amount': payment.total,
            'bill_number': payment.bill_number,
            'bill_date': payment.bill_date,
            'bill_time': payment.bill_time
        })
        request.session['data'] = data

    return JsonResponse({'payments': data})


def admin_bill(request, payment_id):
        # ✅ now read from URL instead of session
    payment = get_object_or_404(Payment, id=payment_id)

    order = payment.order  # ✅ Direct link to Order
    items = order.items.select_related("item")

   # Summarize items
    grouped_items = defaultdict(lambda: {'qty': 0, 'price': 0, 'name': ''})
    for order_item in items:
        item = order_item.item
        grouped_items[item.id]['qty'] += order_item.quantity
        grouped_items[item.id]['price'] = item.price
        grouped_items[item.id]['name'] = item.name

    summarized_items = [
        {
            'name': v['name'],
            'price': v['price'],
            'qty': v['qty'],
            'amount': round(v['qty'] * v['price'], 2)
        }
        for v in grouped_items.values()
    ]

    payment.notified = True
    payment.save()

    return render(request, 'pay_confirm.html', {
        'items_summary': summarized_items,
        'table': payment.table_number,
        'bill_number': payment.bill_number,
        'bill_date': payment.bill_date,
        'bill_time': payment.bill_time,
        'subtotal': payment.subtotal,
        'tax': payment.tax,
        'service_charge': payment.service_charge,
        'total': payment.total,
    })


def ok_in_admin(request, payment_id):
    payments = get_object_or_404(Payment, id=payment_id)

    payments.notified = True
    payments.save()

    page = request.session.get('page')
    return redirect(f"{reverse('admin_dashboard')}?page={page}")

def check_order_status(request, order_id):
    try:
        order = Order.objects.get(id=order_id)
        data = {
            'status': order.status,
            'is_notified': order.is_notified,
        }
        return JsonResponse(data)
    except Order.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)
    
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def mark_order_notified(request, order_id):
    if request.method == 'POST':
        try:
            order = Order.objects.get(id=order_id)
            order.is_notified = True
            order.save()
            return JsonResponse({'status': 'success'})
        except Order.DoesNotExist:
            return JsonResponse({'error': 'Order not found'}, status=404)


def add_table_user(request):
    if request.method == "POST":
        form = TableUserForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "New table user created successfully!")
            return redirect(f"{reverse('admin_dashboard')}?page=settings")
    else:
        form = TableUserForm()
    return render(request, "add_table_user.html", {"form": form})


def reset_table_password(request, user_id):
    user = get_object_or_404(User, id=user_id, is_staff=False, is_superuser=False)
    if request.method == "POST":
        form = TablePasswordResetForm(user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Password updated for {user.username}")
            return redirect(f"{reverse('admin_dashboard')}?page=settings")
    else:
        form = TablePasswordResetForm(user)
    return render(request, "reset_table_password.html", {"form": form, "user": user})

def delete_table_user(request, user_id):
    user = get_object_or_404(User, id=user_id, is_staff=False, is_superuser=False)
    if request.method in ["GET", "POST"]:
        user.delete()
        messages.success(request, f"Deleted user {user.username}")
        return redirect(f"{reverse('admin_dashboard')}?page=settings")

def force_logout_user(request, user_id):
    user = get_object_or_404(User, id=user_id, is_staff=False, is_superuser=False)

    sessions = Session.objects.all()
    count = 0
    for session in sessions:
        data = session.get_decoded()
        if data.get('_auth_user_id') == str(user.id):
            session.delete()
            count += 1

    if count > 0:
        messages.success(request, f"✅ {user.username} has been logged out.")
    else:
        messages.warning(request, f"⚠️ {user.username} is not currently logged in.")

    return redirect(f"{reverse('admin_dashboard')}?page=settings")

def force_logout_all_tables(request):
    # Get all non-admin users (tables only)
    table_users = User.objects.filter(is_staff=False, is_superuser=False)

    # Delete all active sessions for those users
    sessions = Session.objects.all()
    count = 0
    for session in sessions:
        data = session.get_decoded()
        user_id = data.get('_auth_user_id')
        if user_id and table_users.filter(id=user_id).exists():
            session.delete()
            count += 1

    messages.success(request, f"Force logged out {count} table(s).")
    return redirect(f"{reverse('admin_dashboard')}?page=settings")

def delete_feedback(request, payment_id):
    feedback = get_object_or_404(Payment, id=payment_id)
    feedback.feedback = None
    feedback.rating = None
    feedback.save()
    messages.success(request, "Feedback deleted successfully.")
    return redirect(f"{reverse('admin_dashboard')}?page=feedback")

# ✅ Add Group
def add_group(request):
    if request.method == "POST":
        name = request.POST.get("name")
        if name:
            Group.objects.create(name=name)
            messages.success(request, f"Group '{name}' created successfully.")
            return redirect(f"{reverse('admin_dashboard')}?page=settings&set_sub=group")  # update with your dashboard name
        else:
            messages.error(request, "Group name cannot be empty.")
    return render(request, "add_group.html")


# ✅ Edit Group
def edit_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if request.method == "POST":
        name = request.POST.get("name")
        if name:
            group.name = name
            group.save()
            messages.success(request, f"Group '{name}' updated successfully.")
            return redirect(f"{reverse('admin_dashboard')}?page=settings&set_sub=group")
        else:
            messages.error(request, "Group name cannot be empty.")

    return render(request, "edit_group.html", {"group": group})


# ✅ Delete Group
def delete_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    group_name = group.name
    group.delete()
    messages.success(request, f"Group '{group_name}' deleted successfully.")
    return redirect(f"{reverse('admin_dashboard')}?page=settings&set_sub=group")

def manage_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        if user_id:
            user = User.objects.get(id=user_id)
            group.user_set.add(user)
            return redirect("manage_group", group_id=group.id)

    # Users not in this group (for dropdown)
    available_users = User.objects.exclude(groups=group)

    return render(request, "manage_group.html", {
        "group": group,
        "available_users": available_users,
    })


def remove_user_from_group(request, group_id, user_id):
    group = get_object_or_404(Group, id=group_id)
    user = get_object_or_404(User, id=user_id)
    group.user_set.remove(user)
    return redirect("manage_group", group_id=group.id)

from .forms import EmployeeForm   # we’ll create this form

def add_employee(request):
    staff_filter = request.session.get('staff')
    if request.method == "POST":
        form = EmployeeForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Employee added successfully.")
            return redirect(f"{reverse('admin_dashboard')}?page=staff&staff={staff_filter}")  # go back to dashboard
    else:
        form = EmployeeForm()

    return render(request, 'add_employee.html', {'form': form,
        'staff_filter': staff_filter
        },)

def edit_employee(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id)
    staff_filter = request.session.get('staff')

    if request.method == "POST":
        form = EmployeeForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, "Employee updated successfully.")
            return redirect(f"{reverse('admin_dashboard')}?page=staff&staff={staff_filter}")  # back to dashboard
    else:
        form = EmployeeForm(instance=employee)

    return render(request, 'edit_employee.html', {
        'form': form, 
        'employee': employee,
        'staff_filter': staff_filter
        })