from django.shortcuts import render, redirect, get_object_or_404
from owner.models import MenuItem, Order
from django.contrib import messages
from django.urls import reverse
from collections import defaultdict
from django.utils import timezone



def kitchen(request):
    items = MenuItem.objects.all()
    search_query = request.GET.get('q', '').strip()
    
    context = {}
    if request.method == 'POST':
        order_id = request.POST.get('order_id')
        action = request.POST.get('action')
        order = get_object_or_404(Order, id=order_id)

        if action == 'progress':
            if order.status == 'Accept':
                order.status = 'Ready'
            elif order.status == 'Ready':
                order.status = 'Delivered'
            order.save()

        elif action == 'remove':
            order.removed = True
            order.save()

        return redirect('kitchen')
    
    if search_query:
        items = items.filter(name__icontains=search_query)

    # All current visible orders
    orders = Order.objects.filter(removed=False).order_by('created_at')

    # Total quantity of each item across all non-delivered orders
    item_totals = defaultdict(lambda: {'total_qty': 0, 'tables': set()})

    for order in orders:
        if order.status != 'Delivered':
            for item in order.items.all():
                name = item.item.name
                item_totals[name]['total_qty'] += item.quantity
                item_totals[name]['tables'].add(f"{order.table_number}")

    # Convert to flat list for easy rendering
    kitchen_totals = []
    for item_name, data in item_totals.items():
        kitchen_totals.append({
            'item_name': item_name,
            'total_qty': data['total_qty'],
            'tables': ", ".join(sorted(data['tables'])),
        })

    # Stats
    today = timezone.now().date()
    pending_count = Order.objects.filter(status='Accept', removed=False).count()
    preparing_count = Order.objects.filter(status='Ready', removed=False).count()
    completed_count = Order.objects.filter(status='Delivered', created_at__date=today).count()

    return render(request, 'kitchen2.html', {
        'orders': orders,
        'pending_count': pending_count,
        'preparing_count': preparing_count,
        'completed_count': completed_count,
        'kitchen_totals': kitchen_totals,
        'menu_items': items,
        'q': search_query,
    })



def toggle_availability(request, item_id):
    item = get_object_or_404(MenuItem, id=item_id)
    category =  request.session.get('category')
    user = request.GET.get('user')
    if item.delete_status == MenuItem.AVAILABLE:
        item.delete_status = MenuItem.OUT_OF_STOCK
        messages.error(request, f"'{item.name}' marked as Out of Stock.")
    else:
        item.delete_status = MenuItem.AVAILABLE
        messages.success(request, f"'{item.name}' marked as Available.")
    item.save()
    if user == "admin":
        return redirect(f"{reverse('admin_dashboard')}?page=menu&category={category}")
    else:
        return redirect('kitchen')
    