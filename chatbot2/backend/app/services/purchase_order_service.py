import re
from datetime import date

from sqlalchemy.orm import Session, joinedload

from .. import models
from .order_service import find_product


def normalize_po_number(raw: str) -> str:
    raw = raw.strip()
    match = re.search(r"(\d+)", raw)
    if match:
        return f"PO-{match.group(1)}"
    return raw if raw.startswith("PO-") else raw


def next_po_number(db: Session) -> str:
    max_num = 5000
    for (po_number,) in db.query(models.PurchaseOrder.po_number).all():
        match = re.search(r"(\d+)", po_number or "")
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"PO-{max_num + 1}"


def find_supplier(db: Session, supplier_name: str = "") -> models.Supplier | None:
    term = supplier_name.strip()
    if term:
        supplier = db.query(models.Supplier).filter(models.Supplier.name.ilike(f"%{term}%")).first()
        if supplier:
            return supplier
    return db.query(models.Supplier).order_by(models.Supplier.id).first()


def find_supplier_for_product(
    db: Session,
    product: models.Product,
    supplier_name: str = "",
) -> models.Supplier | None:
    if supplier_name.strip():
        supplier = find_supplier(db, supplier_name)
        if supplier:
            return supplier

    if "bearing" in product.name.lower():
        return db.query(models.Supplier).filter(models.Supplier.name.ilike("%bearing%")).first()

    return db.query(models.Supplier).order_by(models.Supplier.id).first()


def create_purchase_order(
    db: Session,
    product_name_or_sku: str,
    quantity: int,
    supplier_name: str = "",
) -> dict:
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")

    product = find_product(db, product_name_or_sku)
    if not product:
        raise ValueError(f"Product not found: {product_name_or_sku}")

    supplier = find_supplier_for_product(db, product, supplier_name)
    if not supplier:
        raise ValueError("No supplier found")

    po_number = next_po_number(db)
    total_amount = product.unit_price * quantity
    po = models.PurchaseOrder(
        po_number=po_number,
        supplier_id=supplier.id,
        status="pending",
        total_amount=total_amount,
        order_date=date.today(),
    )
    db.add(po)
    db.flush()

    db.add(
        models.PurchaseOrderItem(
            purchase_order_id=po.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=product.unit_price,
        )
    )
    db.flush()

    return {
        "success": True,
        "created_purchase_order": True,
        "po_number": po.po_number,
        "supplier_name": supplier.name,
        "product": product.name,
        "sku": product.sku,
        "quantity": quantity,
        "status": po.status,
        "total_amount": total_amount,
        "erp_updated": True,
    }


def get_purchase_order_details(db: Session, po_number: str) -> dict:
    key = normalize_po_number(po_number)
    po = (
        db.query(models.PurchaseOrder)
        .options(
            joinedload(models.PurchaseOrder.supplier),
            joinedload(models.PurchaseOrder.items).joinedload(models.PurchaseOrderItem.product),
        )
        .filter(models.PurchaseOrder.po_number == key)
        .first()
    )
    if not po:
        raise ValueError(f"Purchase order not found: {key}")

    return {
        "success": True,
        "po_number": po.po_number,
        "supplier_name": po.supplier.name if po.supplier else None,
        "status": po.status,
        "total_amount": po.total_amount,
        "order_date": str(po.order_date),
        "items": [
            {
                "product": item.product.name,
                "sku": item.product.sku,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
            }
            for item in po.items
        ],
    }


def receive_purchase_order(db: Session, po_number: str) -> dict:
    key = normalize_po_number(po_number)
    po = (
        db.query(models.PurchaseOrder)
        .options(joinedload(models.PurchaseOrder.items).joinedload(models.PurchaseOrderItem.product))
        .filter(models.PurchaseOrder.po_number == key)
        .first()
    )
    if not po:
        raise ValueError(f"Purchase order not found: {key}")
    if po.status == "received":
        return {
            "success": True,
            "po_number": po.po_number,
            "status": po.status,
            "message": "Purchase order was already received",
            "erp_updated": False,
        }

    received_items = []
    for item in po.items:
        item.product.stock_qty += item.quantity
        db.add(
            models.InventoryMovement(
                product_id=item.product_id,
                movement_type="in",
                quantity=item.quantity,
                reference=po.po_number,
                notes=f"Received purchase order {po.po_number}",
            )
        )
        received_items.append(
            {
                "product": item.product.name,
                "sku": item.product.sku,
                "quantity_received": item.quantity,
                "new_stock_qty": item.product.stock_qty,
            }
        )

    old_status = po.status
    po.status = "received"
    db.flush()

    return {
        "success": True,
        "po_number": po.po_number,
        "old_status": old_status,
        "new_status": po.status,
        "received_items": received_items,
        "erp_updated": True,
    }
