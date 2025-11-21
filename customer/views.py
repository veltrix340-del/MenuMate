from django.shortcuts import render, redirect
from owner.models import MenuItem, Order, Charges, OrderItem, Payment
import uuid
from django.contrib import messages
from collections import defaultdict
from datetime import datetime
from owner.utils import generate_upi_qr
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import json

def logo(request):
    return render(request, 'logo.html')

def calculate_cart_totals(cart):
    """
    Calculate subtotal, tax, service charge, and total for a given cart.
    Cart is a list of dicts: [{'item_id', 'name', 'quantity', 'total', 'ordered', ...}, ...]
    Returns a dict with all values.
    """
    subtotal = sum(item['total'] for item in cart)
    charges = Charges.objects.first()
    tax = round(subtotal * (charges.tax / 100), 2) if charges else 0
    service_charge = round(subtotal * (charges.service_charge / 100), 2) if charges else 0
    total = round(subtotal + tax + service_charge, 2)
    
    return {
        'subtotal': round(subtotal, 2),
        'tax': tax,
        'service_charge': service_charge,
        'total': total
    }


@login_required
def customer_dashboard(request):
    if not request.session.get('visit_id'):
        request.session['visit_id'] = uuid.uuid4().hex  # unique per customer

    bites_items = MenuItem.objects.filter(category='Bites', delete_status=MenuItem.AVAILABLE)
    brews_items = MenuItem.objects.filter(category='Brews', delete_status=MenuItem.AVAILABLE)

    return render(request, 'casa.html', {
        'bites_items': bites_items,
        'brews_items': brews_items,
        'enable_idle_redirect': True,
    })

@login_required
def product_view(request, product_type, product_id):
    product = MenuItem.objects.get(id=product_id)
    order_placed = False

    if request.method == 'POST':
        quantity = int(request.POST.get('quantity') or 1)

        cart = request.session.get('cart', [])
        request.session['customer_name'] = request.session.get('customer_name') or "Guest"

        # Merge only if same item exists AND not ordered
        merged = False
        for item in cart:
            if item['item_id'] == product.id and not item.get('ordered'):
                item['quantity'] += quantity
                item['total'] = round(product.price * item['quantity'], 2)
                merged = True
                break

        if not merged:
            cart.append({
                'uuid': uuid.uuid4().hex,
                'name': product.name,
                'quantity': quantity,
                'total': round(product.price * quantity, 2),
                'ordered': False,
                'item_id': product.id,
            })
            order_placed = True

        # Update session totals
        totals = calculate_cart_totals(cart)
        request.session['cart'] = cart
        request.session['total_amount'] = totals['total']

        return redirect('product_view', product_type=product_type, product_id=product_id)

    # Store last visited product
    request.session['last_product_type'] = product_type
    request.session['last_product_id'] = product_id

    table = int(request.user.username.replace('table', ''))
    session_id = request.session.get('visit_id')

    # Fetch the latest *non-removed* order for this table/session
    recent_order = (
        Order.objects.filter(table_number=table, session_id=session_id, removed=False)
        .exclude(status='Delivered')
        .order_by('-created_at')
        .first()
    )

    current_order = Order.objects.filter(session_id=request.session.get('visit_id'), removed=False).last()
    show_popup = False
    if current_order and current_order.status == "Delivered":
        if request.session.get('delivered_shown_for') != current_order.id:
            show_popup = True
            request.session['delivered_shown_for'] = current_order.id

    return render(request, 'casa.html', {
        'bites_items': MenuItem.objects.filter(category='Bites', delete_status=MenuItem.AVAILABLE),
        'brews_items': MenuItem.objects.filter(category='Brews', delete_status=MenuItem.AVAILABLE),
        'product': product,
        'cart': request.session.get('cart', []),
        'total_amount': request.session.get('total_amount', 0),
        'selected_product_id': product.id,
        'selected_product_type': product_type,
        'show_list': True,
        'order_status': recent_order.status if recent_order else None,
        'order_placed': order_placed,
        'current_order': current_order,
        'show_popup': show_popup,
    })


@login_required
def place_order(request):
    cart = request.session.get('cart', [])
    unplaced_items = [item for item in cart if not item.get('ordered')]

    product_type = request.session.get('last_product_type')
    product_id = request.session.get('last_product_id')
    
    if not unplaced_items:
        messages.error(request, "No new items to order.")
        return redirect('product_view', product_type=product_type, product_id=product_id) if product_type else redirect('customer_dashboard')

    table = int(request.user.username.replace('table', ''))
    session_id = request.session.get('visit_id')

    order = Order.objects.create(table_number=table, session_id=session_id)
    order_uuid = uuid.uuid4().hex

    # Add items to order
    for item in cart:
        if not item.get('ordered'):
            menu_item = MenuItem.objects.get(id=item['item_id'])
            OrderItem.objects.create(
                order=order,
                item=menu_item,
                quantity=item['quantity']
            )
            item['ordered'] = True
            item['order_uuid'] = order_uuid

    # Calculate totals using helper
    totals = calculate_cart_totals(cart)
    request.session['cart'] = cart
    request.session['total_amount'] = totals['total']

    messages.success(request, f"Order placed successfully for Table #{table}!")

    return redirect('product_view', product_type=product_type, product_id=product_id) if product_type else redirect('customer_dashboard')



@login_required
def pay(request):
    table = int(request.user.username.replace('table', ''))
    visit_id = request.session.get('visit_id')

        # Handle AJAX JSON feedback
    if request.method == "POST" and request.headers.get("Content-Type") == "application/json":
        try:
            data = json.loads(request.body)
            rating = data.get("rating")
            feedback_text = data.get("feedback")

            payment = Payment.objects.filter(table_number=table, session_id=visit_id).order_by('-created_at').first()
            if payment:
                payment.rating = int(rating) if rating else None
                payment.feedback = feedback_text
                payment.save()
                return JsonResponse({"status": "success"})  # ✅ must return JSON
            else:
                return JsonResponse({"status": "error", "message": "Payment not found"}, status=400)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)


    # Context for template
    product_type = request.session.get('last_product_type')
    product_id = request.session.get('last_product_id')

    orders = Order.objects.filter(
        table_number=table,
        session_id=visit_id,
    ).prefetch_related('items__item')

    if not orders.exists():
        messages.warning(request, "No orders found. Please place an order before generating the bill.")
        return redirect('product_view', product_type=product_type, product_id=product_id)

    # Group items
    grouped_items = defaultdict(lambda: {'qty': 0, 'price': 0, 'name': ''})
    for order in orders:
        for order_item in order.items.all():
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

    now = datetime.now()
    bill_number = f"#ORD-{table:02d}{now.strftime('%f')[:3]}"
    bill_date = now.strftime("%d/%m/%Y")
    bill_time = now.strftime("%H:%M:%S")

    subtotal = round(sum(i['amount'] for i in summarized_items), 2)

    charges = Charges.objects.first()
    tax = round(subtotal * (charges.tax / 100), 2) if charges else 0
    service_charge = round(subtotal * (charges.service_charge / 100), 2) if charges else 0
    total = round(subtotal + tax + service_charge, 2)

    # Store in session
    request.session['total'] = total
    request.session['bill_number'] = bill_number
    request.session['bill_date'] = bill_date
    request.session['bill_time'] = bill_time

    payment = Payment.objects.filter(table_number=table, session_id=visit_id).order_by('-created_at').first()
    order = Order.objects.filter(table_number=table, session_id=visit_id).order_by('-created_at').first()

    if not payment:
        payment = Payment.objects.create(
            table_number=table,
            session_id=visit_id,
            subtotal=subtotal,
            order=order,
            tax=tax,
            service_charge=service_charge,
            total=total,
            bill_number=bill_number,
            bill_date=bill_date,
            bill_time=bill_time,
        )
    else:
        payment.subtotal = subtotal
        payment.tax = tax
        payment.service_charge = service_charge
        payment.total = total
        payment.bill_number = bill_number
        payment.bill_date = bill_date
        payment.bill_time = bill_time

    return render(request, 'pay_confirm.html', {
        'product_type': product_type,
        'product_id': product_id,
        'orders': orders,
        'items_summary': summarized_items,
        'table': table,
        'bill_number': bill_number,
        'bill_date': bill_date,
        'bill_time': bill_time,
        'subtotal': subtotal,
        'tax': tax,
        'service_charge': service_charge,
        'total': total,
        'payment': payment,   # ✅ pass payment to template
        'stars': range(5, 0, -1),
    })


@login_required
def delete_cart_item(request, uuid):
    cart = request.session.get('cart', [])
    item_to_delete = next((item for item in cart if item['uuid'] == uuid), None)

    if item_to_delete:
        cart = [item for item in cart if item['uuid'] != uuid]
        request.session['cart'] = cart
        request.session['total_amount'] = sum(item['total'] for item in cart)

        messages.success(request, f"{item_to_delete['name']} removed from cart.")

        if cart:
            return redirect('product_view', product_type='Bites' if item_to_delete['item_id'] < 100 else 'Brews', product_id=item_to_delete['item_id'])

    return redirect('customer_dashboard')

@login_required
def clear_orders(request):
    request.session['all_orders'] = []
    return redirect('customer_dashboard')

@login_required
def confirm_cash(request):
    if request.method == 'POST':
        table = int(request.user.username.replace('table', ''))
        visit_id = request.session.get('visit_id')

        payment = Payment.objects.filter(table_number=table, session_id=visit_id).order_by('-created_at').first()
        if payment:
            payment.payment_method = Payment.CASH
            payment.is_paid = True
            payment.save()

    request.session.pop('cart', None)
    request.session.pop('total_amount', None)
    request.session.pop('visit_id', None)
    request.session.pop('customer_name', None)

    messages.success(request, "Please pay the cash to the counter.")
    return redirect('logo')

@login_required
def bill_view(request):
    if request.method == 'POST':
        table = int(request.user.username.replace('table', ''))
        visit_id = request.session.get('visit_id')

        payment = Payment.objects.filter(table_number=table, session_id=visit_id).order_by('-created_at').first()
        if payment:
            payment.payment_method = Payment.ONLINE
            payment.save()

    table_number = request.session.get('table_number')
    total = request.session.get('total')

    upi_id = "gks28112005@okhdfcbank"  # Replace with your actual UPI ID
    name = "Cassa Cassandra"
    
    qr_code = generate_upi_qr(upi_id, name, total)

    return render(request, 'bill.html', {
        "table": table_number,
        "total": total,
        "qr_code": qr_code,
    })

@login_required
def confirm_pay(request):
    if request.method == 'POST':
        table = int(request.user.username.replace('table', ''))
        visit_id = request.session.get('visit_id')

        payment = Payment.objects.filter(table_number=table, session_id=visit_id).order_by('-created_at').first()
        if payment:
            payment.payment_method = Payment.ONLINE
            payment.is_paid = True
            payment.save()

    bill_num = request.session.get('bill_number')
    bill_date = request.session.get('bill_date')
    bill_time = request.session.get('bill_time')
    total = request.session.get('total')

    # Clear session data post-payment
    request.session.pop('cart', None)
    request.session.pop('total_amount', None)
    request.session.pop('visit_id', None)
    request.session.pop('customer_name', None)

    return render(request, 'animation.html', {
        'bill_number': bill_num,
        'bill_date': bill_date,
        'bill_time': bill_time,
        'total': total,
    })

@login_required
def cancel_order(request):
    table = int(request.user.username.replace('table', ''))
    session_id = request.session.get('visit_id')

    product_type = request.session.get('last_product_type')
    product_id = request.session.get('last_product_id')

    latest_order = (
        Order.objects
        .filter(table_number=table, session_id=session_id, removed=False)
        .exclude(status__in=['Ready', 'Delivered'])
        .order_by('-created_at')
        .first()
    )

    if latest_order and latest_order.status == 'Accept':
        # Delete DB Order and Items
        latest_order.delete()

        # Find the UUID from session cart matching this order
        cart = request.session.get('cart', [])
        order_uuid_to_cancel = None

        for item in reversed(cart):
            if item.get('ordered') and 'order_uuid' in item:
                order_uuid_to_cancel = item['order_uuid']
                break

        # Remove only items with that order_uuid
        new_cart = []
        restored_total = 0

        for item in cart:
            if item.get('order_uuid') == order_uuid_to_cancel:
                continue  # 🔥 skip items from this cancelled order
            new_cart.append(item)
            restored_total += item['total']

        request.session['cart'] = new_cart
        request.session['total_amount'] = restored_total

        messages.success(request, "Order canceled successfully!")

    if product_type and product_id:
        return redirect('product_view', product_type=product_type, product_id=product_id)
    else:
        return redirect('customer_dashboard')

@login_required
def if_ready(request):
    messages.warning(request, "Please wait for the order to be ready.")
    return redirect('product_view' , product_type=request.session.get('last_product_type'), product_id=request.session.get('last_product_id'))
