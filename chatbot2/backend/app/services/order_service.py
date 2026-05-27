import re
from datetime import date
from sqlalchemy.orm import Session, joinedload

from .. import models


def normalize_order_name(raw: str) -> str:
    raw = raw.strip()
    match = re.search(r"(\d+)", raw)
    if match:
        return f"Order-{match.group(1)}"
    return raw if raw.startswith("Order-") else raw


def find_product(db: Session, product_name_or_sku: str) -> models.Product | None:
    term = product_name_or_sku.strip()
    product = db.query(models.Product).filter(models.Product.sku == term).first()
    if product:
        return product
    return (
        db.query(models.Product)
        .filter(models.Product.name.ilike(f"%{term}%"))
        .first()
    )


def add_line_item(
    db: Session,
    order_name: str,
    product_name_or_sku: str,
    quantity: int,
) -> dict:
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")

    order_key = normalize_order_name(order_name)
    order = (
        db.query(models.Order)
        .options(joinedload(models.Order.items))
        .filter(models.Order.order_name == order_key)
        .first()
    )
    if not order:
        raise ValueError(f"Order not found: {order_key}")

    product = find_product(db, product_name_or_sku)
    if not product:
        raise ValueError(f"Product not found: {product_name_or_sku}")

    if product.stock_qty < quantity:
        raise ValueError(
            f"Insufficient stock for {product.name}. "
            f"Available: {product.stock_qty}, requested: {quantity}"
        )

    line_total = product.unit_price * quantity
    item = models.OrderItem(
        order_id=order.id,
        product_id=product.id,
        quantity=quantity,
        unit_price=product.unit_price,
    )
    db.add(item)

    order.total_amount = (order.total_amount or 0) + line_total
    product.stock_qty -= quantity

    db.add(
        models.InventoryMovement(
            product_id=product.id,
            movement_type="out",
            quantity=quantity,
            reference=order.order_name,
            notes=f"Allocated to {order.order_name}",
        )
    )
    db.flush()

    return {
        "success": True,
        "order_name": order.order_name,
        "product": product.name,
        "sku": product.sku,
        "quantity_added": quantity,
        "unit_price": product.unit_price,
        "line_total": line_total,
        "new_order_total": order.total_amount,
        "remaining_stock": product.stock_qty,
        "erp_updated": True,
    }


def remove_line_item(
    db: Session,
    order_name: str,
    product_name_or_sku: str,
    quantity: int | None = None,
) -> dict:
    order_key = normalize_order_name(order_name)
    order = (
        db.query(models.Order)
        .options(joinedload(models.Order.items).joinedload(models.OrderItem.product))
        .filter(models.Order.order_name == order_key)
        .first()
    )
    if not order:
        raise ValueError(f"Order not found: {order_key}")

    product = find_product(db, product_name_or_sku)
    if not product:
        raise ValueError(f"Product not found: {product_name_or_sku}")

    matching = [it for it in order.items if it.product_id == product.id]
    if not matching:
        raise ValueError(f"{product.name} is not on {order_key}")

    item = matching[0]
    remove_qty = quantity if quantity is not None else item.quantity
    if remove_qty <= 0 or remove_qty > item.quantity:
        raise ValueError(f"Invalid quantity to remove: {remove_qty} (on order: {item.quantity})")

    line_total = item.unit_price * remove_qty
    if remove_qty == item.quantity:
        db.delete(item)
    else:
        item.quantity -= remove_qty

    order.total_amount = max(0, (order.total_amount or 0) - line_total)
    product.stock_qty += remove_qty
    db.add(
        models.InventoryMovement(
            product_id=product.id,
            movement_type="in",
            quantity=remove_qty,
            reference=order.order_name,
            notes=f"Returned from {order.order_name}",
        )
    )
    db.flush()

    return {
        "success": True,
        "order_name": order.order_name,
        "product": product.name,
        "quantity_removed": remove_qty,
        "new_order_total": order.total_amount,
        "stock_restored": remove_qty,
        "erp_updated": True,
    }


def delete_order(db: Session, order_name: str) -> dict:
    order_key = normalize_order_name(order_name)
    order = (
        db.query(models.Order)
        .options(joinedload(models.Order.items).joinedload(models.OrderItem.product))
        .filter(models.Order.order_name == order_key)
        .first()
    )
    if not order:
        raise ValueError(f"Order not found: {order_key}")

    paid_invoice = (
        db.query(models.Invoice)
        .filter(models.Invoice.order_id == order.id, models.Invoice.status == "paid")
        .first()
    )
    if paid_invoice:
        raise ValueError(f"Cannot delete {order_key}: linked to paid invoice {paid_invoice.invoice_number}")

    restored = []
    for item in list(order.items):
        if item.product:
            item.product.stock_qty += item.quantity
            restored.append({"product": item.product.name, "qty": item.quantity})
        db.delete(item)

    for inv in db.query(models.Invoice).filter(models.Invoice.order_id == order.id).all():
        db.delete(inv)

    for movement in db.query(models.InventoryMovement).filter(models.InventoryMovement.reference == order.order_name).all():
        db.delete(movement)

    name = order.order_name
    db.delete(order)
    db.flush()

    return {
        "success": True,
        "deleted_order": name,
        "inventory_restored": restored,
        "erp_updated": True,
    }


def next_order_name(db: Session) -> str:
    max_num = 1000
    for (order_name,) in db.query(models.Order.order_name).all():
        match = re.search(r"(\d+)", order_name or "")
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"Order-{max_num + 1}"


def find_client(db: Session, client_name: str) -> models.Client | None:
    if not client_name.strip():
        return db.query(models.Client).order_by(models.Client.id).first()
    return db.query(models.Client).filter(models.Client.name.ilike(f"%{client_name.strip()}%")).first()


def create_sales_order(
    db: Session,
    client_name: str,
    product_name_or_sku: str,
    quantity: int,
) -> dict:
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")

    client = find_client(db, client_name)
    if not client:
        raise ValueError(f"Client not found: {client_name or '(none)'}")

    product = find_product(db, product_name_or_sku)
    if not product:
        raise ValueError(f"Product not found: {product_name_or_sku}")

    if product.stock_qty < quantity:
        raise ValueError(
            f"Cannot place order: insufficient stock for {product.name}. "
            f"Available: {product.stock_qty}, requested: {quantity}. "
            f"Ask to replenish stock first or reduce quantity."
        )

    order_name = next_order_name(db)
    order = models.Order(
        order_name=order_name,
        client_id=client.id,
        status="pending",
        total_amount=0.0,
        order_date=date.today(),
        notes="Created via AI assistant",
    )
    db.add(order)
    db.flush()

    result = add_line_item(db, order_name, product_name_or_sku, quantity)
    result["created_order"] = True
    result["client_name"] = client.name
    return result


def get_product_stock(db: Session, product_name_or_sku: str) -> dict:
    product = find_product(db, product_name_or_sku)
    if not product:
        return {"success": False, "error": f"Product not found: {product_name_or_sku}"}
    return {
        "success": True,
        "sku": product.sku,
        "name": product.name,
        "stock_qty": product.stock_qty,
        "reorder_level": product.reorder_level,
        "unit_price": product.unit_price,
    }


def replenish_product_stock(db: Session, product_name_or_sku: str, quantity: int) -> dict:
    if quantity <= 0:
        raise ValueError("Replenish quantity must be positive")
    product = find_product(db, product_name_or_sku)
    if not product:
        raise ValueError(f"Product not found: {product_name_or_sku}")
    product.stock_qty += quantity
    db.add(
        models.InventoryMovement(
            product_id=product.id,
            movement_type="in",
            quantity=quantity,
            reference="AI-restock",
            notes="Stock replenishment via assistant",
        )
    )
    db.flush()
    return {
        "success": True,
        "product": product.name,
        "added_qty": quantity,
        "new_stock_qty": product.stock_qty,
        "erp_updated": True,
    }


def update_product_inventory(
    db: Session,
    product_name_or_sku: str,
    stock_qty: int | None = None,
    reorder_level: int | None = None,
) -> dict:
    product = find_product(db, product_name_or_sku)
    if not product:
        raise ValueError(f"Product not found: {product_name_or_sku}")
    if stock_qty is None and reorder_level is None:
        raise ValueError("Provide stock_qty, reorder_level, or both")
    if stock_qty is not None and stock_qty < 0:
        raise ValueError("Stock quantity cannot be negative")
    if reorder_level is not None and reorder_level < 0:
        raise ValueError("Reorder level cannot be negative")

    old_stock_qty = product.stock_qty
    old_reorder_level = product.reorder_level

    if stock_qty is not None:
        product.stock_qty = stock_qty
    if reorder_level is not None:
        product.reorder_level = reorder_level

    db.flush()
    return {
        "success": True,
        "inventory_updated": True,
        "sku": product.sku,
        "product": product.name,
        "old_stock_qty": old_stock_qty,
        "new_stock_qty": product.stock_qty,
        "old_reorder_level": old_reorder_level,
        "new_reorder_level": product.reorder_level,
        "low_stock": product.stock_qty < product.reorder_level,
        "erp_updated": True,
    }
