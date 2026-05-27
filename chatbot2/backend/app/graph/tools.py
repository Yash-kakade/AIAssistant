from datetime import date, timedelta, datetime as dt
from langchain_core.tools import tool
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from ..database import SessionLocal
from .. import models
from ..rag.pipeline import search_manuals, format_manual_context
from ..services.order_service import (
    add_line_item,
    remove_line_item,
    delete_order,
    create_sales_order,
    get_product_stock,
    replenish_product_stock,
    update_product_inventory,
    normalize_order_name,
    find_product,
)
from ..services.employee_service import (
    add_employee,
    update_employee_salary as apply_employee_salary,
    remove_employee,
)
from ..services.purchase_order_service import (
    create_purchase_order,
    get_purchase_order_details as fetch_purchase_order_details,
    receive_purchase_order,
)


def _with_db(fn):
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()


def _with_db_write(fn):
    db = SessionLocal()
    try:
        result = fn(db)
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@tool
def get_order_metrics():
    """Returns total orders, and counts of pending, completed, and ongoing orders."""
    def query(db: Session):
        total = db.query(func.count(models.Order.id)).scalar() or 0
        pending = db.query(func.count(models.Order.id)).filter(models.Order.status == "pending").scalar() or 0
        complete = db.query(func.count(models.Order.id)).filter(models.Order.status == "completed").scalar() or 0
        ongoing = db.query(func.count(models.Order.id)).filter(models.Order.status == "ongoing").scalar() or 0
        return {"total_orders": total, "pending": pending, "completed": complete, "ongoing": ongoing}
    return _with_db(query)


@tool
def list_orders(status: str = "") -> list:
    """List all sales orders with their names, status, client, and total.
    Optionally filter by status: pending, ongoing, or completed."""
    def query(db: Session):
        q = (
            db.query(models.Order)
            .options(joinedload(models.Order.client))
            .order_by(models.Order.id)
        )
        if status.strip():
            q = q.filter(models.Order.status == status.strip().lower())
        orders = q.all()
        return [
            {
                "order_name": o.order_name,
                "status": o.status,
                "client": o.client.name if o.client else None,
                "total_amount": o.total_amount,
                "order_date": str(o.order_date),
            }
            for o in orders
        ]
    return _with_db(query)


@tool
def bulk_update_order_status(new_status: str, filter_status: str = "") -> dict:
    """Update status of MULTIPLE or ALL sales orders at once.
    new_status: the status to set (pending / ongoing / completed).
    filter_status: only update orders currently in this status. Leave empty to update ALL orders.
    Use this whenever the user says 'mark all orders as X' or 'set all pending orders to Y'."""
    allowed = {"pending", "ongoing", "completed"}
    status = new_status.strip().lower()
    if status not in allowed:
        return {"success": False, "error": f"Status must be one of: {', '.join(sorted(allowed))}"}

    def mutate(db: Session):
        q = db.query(models.Order)
        if filter_status.strip():
            q = q.filter(models.Order.status == filter_status.strip().lower())
        orders = q.all()
        if not orders:
            return {"success": False, "error": "No orders found matching the filter."}
        count = 0
        for order in orders:
            order.status = status
            count += 1
        db.flush()
        return {
            "success": True,
            "updated_count": count,
            "new_status": status,
            "filter_applied": filter_status.strip() or "all orders",
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def get_client_orders(client_name: str):
    """Returns orders associated with a specific client name."""
    def query(db: Session):
        orders = (
            db.query(models.Order)
            .join(models.Client)
            .options(joinedload(models.Order.client))
            .filter(models.Client.name.ilike(f"%{client_name}%"))
            .all()
        )
        if not orders:
            return f"No orders found for client: {client_name}"
        return [
            {"order_name": o.order_name, "status": o.status, "total_amount": o.total_amount, "client": o.client.name}
            for o in orders
        ]
    return _with_db(query)


@tool
def get_order_details(order_name: str):
    """Returns details about an order by its name (e.g. Order-1001) including line items."""
    def query(db: Session):
        order = (
            db.query(models.Order)
            .options(joinedload(models.Order.client), joinedload(models.Order.items).joinedload(models.OrderItem.product))
            .filter(models.Order.order_name == order_name)
            .first()
        )
        if not order:
            return f"Order not found: {order_name}"
        return {
            "order_name": order.order_name,
            "status": order.status,
            "total_amount": order.total_amount,
            "client_name": order.client.name if order.client else None,
            "order_date": str(order.order_date),
            "items": [
                {"product": it.product.name, "sku": it.product.sku, "qty": it.quantity, "unit_price": it.unit_price}
                for it in order.items
            ],
        }
    return _with_db(query)


@tool
def get_machine_info(machine_name: str):
    """Returns status, type, efficiency, location, and manual filename for a machine."""
    def query(db: Session):
        machine = db.query(models.Machine).filter(models.Machine.name.ilike(f"%{machine_name}%")).first()
        if not machine:
            return f"Machine not found: {machine_name}"
        return {
            "name": machine.name,
            "type": machine.type,
            "status": machine.status,
            "efficiency": machine.efficiency,
            "location": machine.location,
            "serial_number": machine.serial_number,
            "manual_file": machine.manual_file,
        }
    return _with_db(query)


@tool
def get_all_machines():
    """Returns all machines on the factory floor with status and efficiency."""
    def query(db: Session):
        machines = db.query(models.Machine).order_by(models.Machine.name).all()
        return [
            {"name": m.name, "type": m.type, "status": m.status, "efficiency": m.efficiency, "location": m.location}
            for m in machines
        ]
    return _with_db(query)


@tool
def get_inventory_summary():
    """Returns product inventory summary including low-stock items."""
    def query(db: Session):
        products = db.query(models.Product).order_by(models.Product.stock_qty).all()
        low_stock = [p for p in products if p.stock_qty < p.reorder_level]
        return {
            "total_products": len(products),
            "low_stock_count": len(low_stock),
            "low_stock_items": [
                {"sku": p.sku, "name": p.name, "stock_qty": p.stock_qty, "reorder_level": p.reorder_level}
                for p in low_stock
            ],
            "top_products": [
                {"sku": p.sku, "name": p.name, "stock_qty": p.stock_qty, "unit_price": p.unit_price}
                for p in products[:5]
            ],
        }
    return _with_db(query)


@tool
def get_invoice_summary():
    """Returns invoice counts by status and total pending/overdue amounts."""
    def query(db: Session):
        invoices = db.query(models.Invoice).all()
        by_status = {}
        for inv in invoices:
            by_status[inv.status] = by_status.get(inv.status, 0) + 1
        pending_amount = sum(i.amount for i in invoices if i.status in ("pending", "overdue"))
        return {"count_by_status": by_status, "pending_overdue_total": pending_amount}
    return _with_db(query)


@tool
def check_product_stock(product_name_or_sku: str):
    """Check available inventory before placing an order."""
    return _with_db(lambda db: get_product_stock(db, product_name_or_sku))


@tool
def replenish_stock(product_name_or_sku: str, quantity: int):
    """Add inventory (warehouse restock) when stock is too low to fulfill an order."""
    return _with_db_write(lambda db: replenish_product_stock(db, product_name_or_sku, quantity))


@tool
def update_inventory_record(
    product_name_or_sku: str,
    stock_qty: int | None = None,
    reorder_level: int | None = None,
):
    """Update a product inventory record. Use this to set exact stock_qty and/or reorder_level, including removing a low-stock alert."""
    return _with_db_write(
        lambda db: update_product_inventory(db, product_name_or_sku, stock_qty, reorder_level)
    )


@tool
def create_supplier_purchase_order(
    product_name_or_sku: str,
    quantity: int,
    supplier_name: str = "",
):
    """Create a NEW supplier purchase order for restocking inventory. Use this when the user asks to order/buy stock from a supplier or create a purchase order."""
    return _with_db_write(
        lambda db: create_purchase_order(db, product_name_or_sku, quantity, supplier_name)
    )


@tool
def get_purchase_order_details(po_number: str):
    """Return supplier purchase order details by PO number, including product line items."""
    def query(db: Session):
        try:
            return fetch_purchase_order_details(db, po_number)
        except ValueError as e:
            return {"success": False, "error": str(e)}
    return _with_db(query)


@tool
def receive_supplier_purchase_order(po_number: str):
    """Confirm supplier goods were received for a purchase order. This marks the PO received and adds the ordered quantities into inventory."""
    return _with_db_write(lambda db: receive_purchase_order(db, po_number))


@tool
def place_product_order(
    product_name_or_sku: str,
    quantity: int,
    order_name: str = "",
    client_name: str = "",
):
    """Place a product order. If order_name is empty, creates a NEW sales order. Always check stock first; if insufficient, use replenish_stock then retry.
    Use when user says they ordered/bought/want units without naming an existing order number."""
    def mutate(db: Session):
        if order_name.strip():
            return add_line_item(db, order_name, product_name_or_sku, quantity)
        return create_sales_order(db, client_name, product_name_or_sku, quantity)
    return _with_db_write(mutate)


@tool
def add_order_line_item(order_name: str, product_name_or_sku: str, quantity: int):
    """Add a product line item to an EXISTING sales order (must include order number).
    order_name: e.g. Order-1006 or 1006. product_name_or_sku: product name or SKU like PRD-006."""
    return _with_db_write(lambda db: add_line_item(db, order_name, product_name_or_sku, quantity))


@tool
def remove_order_line_item(order_name: str, product_name_or_sku: str, quantity: int = 0):
    """Remove a product line from an order and restore inventory. quantity=0 removes entire line."""
    qty = quantity if quantity > 0 else None
    return _with_db_write(lambda db: remove_line_item(db, order_name, product_name_or_sku, qty))


@tool
def remove_order(order_name: str):
    """Delete/cancel a sales order, restore stock for all line items. Fails if order has a paid invoice."""
    return _with_db_write(lambda db: delete_order(db, order_name))


@tool
def add_employee_record(
    name: str,
    email: str,
    role: str,
    salary: float,
    department_name: str = "",
):
    """Add a new employee to the ERP. salary is annual salary in USD."""
    return _with_db_write(
        lambda db: add_employee(db, name, email, role, salary, department_name)
    )


@tool
def update_employee_salary(
    employee_name_or_email: str,
    new_salary: float = 0,
    increase_by: float = 0,
):
    """Set or raise an employee's salary. Use new_salary for absolute amount, or increase_by to add to current salary."""
    def mutate(db: Session):
        if increase_by > 0:
            result = apply_employee_salary(db, employee_name_or_email, new_salary=0, increase_by=increase_by)
        elif new_salary > 0:
            result = apply_employee_salary(db, employee_name_or_email, new_salary=new_salary, increase_by=None)
        else:
            return {"success": False, "error": "Provide new_salary or increase_by"}
        result["erp_updated"] = True
        return result
    return _with_db_write(mutate)


@tool
def remove_employee_record(employee_name_or_email: str):
    """Remove an employee from the system by name or email."""
    return _with_db_write(lambda db: remove_employee(db, employee_name_or_email))


@tool
def update_order_status(order_name: str, new_status: str):
    """Update an order's status. new_status must be one of: pending, ongoing, completed."""
    allowed = {"pending", "ongoing", "completed"}
    status = new_status.strip().lower()
    if status not in allowed:
        return {"success": False, "error": f"Status must be one of: {', '.join(sorted(allowed))}"}

    def mutate(db: Session):
        key = normalize_order_name(order_name)
        order = db.query(models.Order).filter(models.Order.order_name == key).first()
        if not order:
            return {"success": False, "error": f"Order not found: {key}"}
        old = order.status
        order.status = status
        return {
            "success": True,
            "order_name": order.order_name,
            "old_status": old,
            "new_status": status,
            "erp_updated": True,
        }

    return _with_db_write(mutate)


@tool
def search_machine_manual(query: str, machine_name: str = ""):
    """Search machine operation manuals (PDF) for setup, safety, maintenance, troubleshooting, and specifications.
    Use when the user asks about manuals, procedures, safety, calibration, or how to operate a machine.
    Pass machine_name when the user refers to a specific machine (e.g. CNC Alpha-1)."""
    results = search_manuals(query=query, machine_name=machine_name or None, top_k=4)
    return format_manual_context(results)


# ── Products ──────────────────────────────────────────────────────────────────

@tool
def create_product(
    sku: str,
    name: str,
    category: str,
    unit_price: float,
    stock_qty: int = 0,
    reorder_level: int = 10,
) -> dict:
    """Create a NEW product in the ERP catalog.
    sku: unique product code (e.g. HYD-001).
    Set stock_qty >= reorder_level so no low-stock alert is triggered.
    Use this whenever the user asks to add/create a new product or item."""
    def mutate(db: Session):
        existing = db.query(models.Product).filter(models.Product.sku == sku.strip().upper()).first()
        if existing:
            return {"success": False, "error": f"Product with SKU {sku.upper()} already exists: {existing.name}"}
        product = models.Product(
            sku=sku.strip().upper(),
            name=name.strip(),
            category=category.strip(),
            unit_price=unit_price,
            stock_qty=stock_qty,
            reorder_level=reorder_level,
        )
        db.add(product)
        db.flush()
        return {
            "success": True,
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "unit_price": product.unit_price,
            "stock_qty": product.stock_qty,
            "reorder_level": product.reorder_level,
            "low_stock_alert": product.stock_qty < product.reorder_level,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def list_products(category: str = "") -> list:
    """List all products in the catalog. Optionally filter by category."""
    def query(db: Session):
        q = db.query(models.Product).order_by(models.Product.name)
        if category.strip():
            q = q.filter(models.Product.category.ilike(f"%{category.strip()}%"))
        products = q.all()
        return [
            {
                "sku": p.sku,
                "name": p.name,
                "category": p.category,
                "unit_price": p.unit_price,
                "stock_qty": p.stock_qty,
                "reorder_level": p.reorder_level,
                "low_stock": p.stock_qty < p.reorder_level,
            }
            for p in products
        ]
    return _with_db(query)


@tool
def update_product(
    product_name_or_sku: str,
    name: str = "",
    category: str = "",
    unit_price: float = 0.0,
) -> dict:
    """Update an existing product's name, category, or unit price."""
    def mutate(db: Session):
        product = find_product(db, product_name_or_sku)
        if not product:
            return {"success": False, "error": f"Product not found: {product_name_or_sku}"}
        if name.strip():
            product.name = name.strip()
        if category.strip():
            product.category = category.strip()
        if unit_price > 0:
            product.unit_price = unit_price
        db.flush()
        return {
            "success": True,
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "unit_price": product.unit_price,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def delete_product(product_name_or_sku: str) -> dict:
    """Delete a product from the catalog. Fails if the product is used in any existing order."""
    def mutate(db: Session):
        product = find_product(db, product_name_or_sku)
        if not product:
            return {"success": False, "error": f"Product not found: {product_name_or_sku}"}
        in_orders = db.query(models.OrderItem).filter(models.OrderItem.product_id == product.id).count()
        if in_orders > 0:
            return {"success": False, "error": f"Cannot delete {product.name}: used in {in_orders} order(s)"}
        name, sku = product.name, product.sku
        db.delete(product)
        db.flush()
        return {"success": True, "deleted_product": name, "sku": sku, "erp_updated": True}
    return _with_db_write(mutate)


# ── Clients ───────────────────────────────────────────────────────────────────

@tool
def add_client(
    name: str,
    email: str = "",
    company: str = "",
    phone: str = "",
) -> dict:
    """Add a new client to the ERP."""
    def mutate(db: Session):
        client = models.Client(
            name=name.strip(),
            email=email.strip() or None,
            company=company.strip() or None,
            phone=phone.strip() or None,
        )
        db.add(client)
        db.flush()
        return {
            "success": True,
            "id": client.id,
            "name": client.name,
            "email": client.email,
            "company": client.company,
            "phone": client.phone,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def update_client(
    client_name: str,
    new_name: str = "",
    email: str = "",
    company: str = "",
    phone: str = "",
) -> dict:
    """Update a client's details (name, email, company, phone)."""
    def mutate(db: Session):
        client = db.query(models.Client).filter(models.Client.name.ilike(f"%{client_name.strip()}%")).first()
        if not client:
            return {"success": False, "error": f"Client not found: {client_name}"}
        if new_name.strip():
            client.name = new_name.strip()
        if email.strip():
            client.email = email.strip()
        if company.strip():
            client.company = company.strip()
        if phone.strip():
            client.phone = phone.strip()
        db.flush()
        return {
            "success": True,
            "id": client.id,
            "name": client.name,
            "email": client.email,
            "company": client.company,
            "phone": client.phone,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def remove_client(client_name: str) -> dict:
    """Remove a client from the ERP. Fails if they have pending or ongoing orders."""
    def mutate(db: Session):
        client = db.query(models.Client).filter(models.Client.name.ilike(f"%{client_name.strip()}%")).first()
        if not client:
            return {"success": False, "error": f"Client not found: {client_name}"}
        active = db.query(models.Order).filter(
            models.Order.client_id == client.id,
            models.Order.status.in_(["pending", "ongoing"]),
        ).count()
        if active > 0:
            return {"success": False, "error": f"Cannot remove {client.name}: has {active} active order(s)"}
        name = client.name
        db.delete(client)
        db.flush()
        return {"success": True, "deleted_client": name, "erp_updated": True}
    return _with_db_write(mutate)


@tool
def list_clients() -> list:
    """List all clients in the ERP."""
    def query(db: Session):
        clients = db.query(models.Client).order_by(models.Client.name).all()
        return [
            {"id": c.id, "name": c.name, "email": c.email, "company": c.company, "phone": c.phone}
            for c in clients
        ]
    return _with_db(query)


# ── Suppliers ─────────────────────────────────────────────────────────────────

@tool
def add_supplier(
    name: str,
    email: str = "",
    phone: str = "",
    company: str = "",
) -> dict:
    """Add a new supplier to the ERP."""
    def mutate(db: Session):
        supplier = models.Supplier(
            name=name.strip(),
            email=email.strip() or None,
            phone=phone.strip() or None,
            company=company.strip() or None,
        )
        db.add(supplier)
        db.flush()
        return {
            "success": True,
            "id": supplier.id,
            "name": supplier.name,
            "email": supplier.email,
            "company": supplier.company,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def update_supplier(
    supplier_name: str,
    new_name: str = "",
    email: str = "",
    phone: str = "",
    company: str = "",
) -> dict:
    """Update a supplier's details (name, email, phone, company)."""
    def mutate(db: Session):
        supplier = db.query(models.Supplier).filter(models.Supplier.name.ilike(f"%{supplier_name.strip()}%")).first()
        if not supplier:
            return {"success": False, "error": f"Supplier not found: {supplier_name}"}
        if new_name.strip():
            supplier.name = new_name.strip()
        if email.strip():
            supplier.email = email.strip()
        if phone.strip():
            supplier.phone = phone.strip()
        if company.strip():
            supplier.company = company.strip()
        db.flush()
        return {
            "success": True,
            "id": supplier.id,
            "name": supplier.name,
            "email": supplier.email,
            "phone": supplier.phone,
            "company": supplier.company,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def remove_supplier(supplier_name: str) -> dict:
    """Remove a supplier. Fails if they have open purchase orders."""
    def mutate(db: Session):
        supplier = db.query(models.Supplier).filter(models.Supplier.name.ilike(f"%{supplier_name.strip()}%")).first()
        if not supplier:
            return {"success": False, "error": f"Supplier not found: {supplier_name}"}
        open_pos = db.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.supplier_id == supplier.id,
            models.PurchaseOrder.status.in_(["pending", "ordered"]),
        ).count()
        if open_pos > 0:
            return {"success": False, "error": f"Cannot remove {supplier.name}: has {open_pos} open purchase order(s)"}
        name = supplier.name
        db.delete(supplier)
        db.flush()
        return {"success": True, "deleted_supplier": name, "erp_updated": True}
    return _with_db_write(mutate)


@tool
def list_suppliers() -> list:
    """List all suppliers in the ERP."""
    def query(db: Session):
        suppliers = db.query(models.Supplier).order_by(models.Supplier.name).all()
        return [
            {"id": s.id, "name": s.name, "email": s.email, "phone": s.phone, "company": s.company}
            for s in suppliers
        ]
    return _with_db(query)


# ── Machines ──────────────────────────────────────────────────────────────────

@tool
def add_machine(
    name: str,
    machine_type: str,
    status: str = "operational",
    efficiency: float = 100.0,
    location: str = "",
    serial_number: str = "",
) -> dict:
    """Add a new machine to the factory floor."""
    def mutate(db: Session):
        existing = db.query(models.Machine).filter(models.Machine.name.ilike(name.strip())).first()
        if existing:
            return {"success": False, "error": f"Machine already exists: {name}"}
        machine = models.Machine(
            name=name.strip(),
            type=machine_type.strip(),
            status=status.strip().lower(),
            efficiency=efficiency,
            location=location.strip() or None,
            serial_number=serial_number.strip() or None,
        )
        db.add(machine)
        db.flush()
        return {
            "success": True,
            "id": machine.id,
            "name": machine.name,
            "type": machine.type,
            "status": machine.status,
            "efficiency": machine.efficiency,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def update_machine(
    machine_name: str,
    status: str = "",
    efficiency: float = -1.0,
    location: str = "",
) -> dict:
    """Update a machine's status (operational/maintenance/offline), efficiency (0-100), or location."""
    def mutate(db: Session):
        machine = db.query(models.Machine).filter(models.Machine.name.ilike(f"%{machine_name.strip()}%")).first()
        if not machine:
            return {"success": False, "error": f"Machine not found: {machine_name}"}
        if status.strip():
            machine.status = status.strip().lower()
        if efficiency >= 0:
            machine.efficiency = efficiency
        if location.strip():
            machine.location = location.strip()
        db.flush()
        return {
            "success": True,
            "name": machine.name,
            "status": machine.status,
            "efficiency": machine.efficiency,
            "location": machine.location,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def remove_machine(machine_name: str) -> dict:
    """Remove a machine from the system."""
    def mutate(db: Session):
        machine = db.query(models.Machine).filter(models.Machine.name.ilike(f"%{machine_name.strip()}%")).first()
        if not machine:
            return {"success": False, "error": f"Machine not found: {machine_name}"}
        name = machine.name
        db.delete(machine)
        db.flush()
        return {"success": True, "deleted_machine": name, "erp_updated": True}
    return _with_db_write(mutate)


# ── Maintenance ───────────────────────────────────────────────────────────────

@tool
def list_maintenance_logs(machine_name: str = "", status: str = "") -> list:
    """List maintenance logs. Filter by machine_name or status (scheduled/in_progress/completed)."""
    def query(db: Session):
        q = (
            db.query(models.MaintenanceLog)
            .options(joinedload(models.MaintenanceLog.machine))
            .order_by(models.MaintenanceLog.scheduled_date.desc())
        )
        if machine_name.strip():
            q = q.join(models.Machine).filter(models.Machine.name.ilike(f"%{machine_name.strip()}%"))
        if status.strip():
            q = q.filter(models.MaintenanceLog.status == status.strip().lower())
        return [
            {
                "id": log.id,
                "machine": log.machine.name if log.machine else None,
                "type": log.maintenance_type,
                "description": log.description,
                "scheduled_date": str(log.scheduled_date),
                "completed_date": str(log.completed_date) if log.completed_date else None,
                "status": log.status,
            }
            for log in q.limit(50).all()
        ]
    return _with_db(query)


@tool
def add_maintenance_log(
    machine_name: str,
    maintenance_type: str,
    description: str,
    scheduled_date: str,
    technician_name: str = "",
    status: str = "scheduled",
) -> dict:
    """Add a maintenance log entry for a machine. scheduled_date format: YYYY-MM-DD.
    maintenance_type examples: preventive, corrective, inspection."""
    def mutate(db: Session):
        machine = db.query(models.Machine).filter(models.Machine.name.ilike(f"%{machine_name.strip()}%")).first()
        if not machine:
            return {"success": False, "error": f"Machine not found: {machine_name}"}
        technician = None
        if technician_name.strip():
            technician = db.query(models.Employee).filter(
                models.Employee.name.ilike(f"%{technician_name.strip()}%")
            ).first()
        try:
            sched = dt.strptime(scheduled_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            return {"success": False, "error": "scheduled_date must be YYYY-MM-DD"}
        log = models.MaintenanceLog(
            machine_id=machine.id,
            technician_id=technician.id if technician else None,
            maintenance_type=maintenance_type.strip(),
            description=description.strip(),
            scheduled_date=sched,
            status=status.strip().lower(),
        )
        db.add(log)
        db.flush()
        return {
            "success": True,
            "id": log.id,
            "machine": machine.name,
            "maintenance_type": maintenance_type,
            "scheduled_date": str(sched),
            "status": log.status,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def update_maintenance_log(
    log_id: int,
    status: str,
    completed_date: str = "",
) -> dict:
    """Update maintenance log status (scheduled/in_progress/completed). Get log_id from list_maintenance_logs."""
    def mutate(db: Session):
        log = db.query(models.MaintenanceLog).filter(models.MaintenanceLog.id == log_id).first()
        if not log:
            return {"success": False, "error": f"Maintenance log #{log_id} not found"}
        log.status = status.strip().lower()
        if completed_date.strip():
            try:
                log.completed_date = dt.strptime(completed_date.strip(), "%Y-%m-%d").date()
            except ValueError:
                return {"success": False, "error": "completed_date must be YYYY-MM-DD"}
        elif status.strip().lower() == "completed" and not log.completed_date:
            log.completed_date = date.today()
        db.flush()
        return {
            "success": True,
            "log_id": log_id,
            "status": log.status,
            "completed_date": str(log.completed_date) if log.completed_date else None,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


# ── Invoices ──────────────────────────────────────────────────────────────────

@tool
def create_invoice(
    client_name: str,
    amount: float,
    order_name: str = "",
    due_days: int = 30,
) -> dict:
    """Create a new invoice for a client. Link to a sales order with order_name if applicable."""
    def mutate(db: Session):
        client = db.query(models.Client).filter(models.Client.name.ilike(f"%{client_name.strip()}%")).first()
        if not client:
            return {"success": False, "error": f"Client not found: {client_name}"}
        order = None
        if order_name.strip():
            key = normalize_order_name(order_name)
            order = db.query(models.Order).filter(models.Order.order_name == key).first()
        today = date.today()
        last = db.query(models.Invoice).order_by(models.Invoice.id.desc()).first()
        inv_num = f"INV-{(last.id + 1) if last else 1:04d}"
        invoice = models.Invoice(
            invoice_number=inv_num,
            order_id=order.id if order else None,
            client_id=client.id,
            amount=amount,
            status="pending",
            issued_date=today,
            due_date=today + timedelta(days=due_days),
        )
        db.add(invoice)
        db.flush()
        return {
            "success": True,
            "invoice_number": invoice.invoice_number,
            "client": client.name,
            "amount": invoice.amount,
            "status": invoice.status,
            "issued_date": str(invoice.issued_date),
            "due_date": str(invoice.due_date),
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def update_invoice_status(invoice_number: str, new_status: str) -> dict:
    """Update an invoice's status. new_status must be one of: pending, paid, overdue, cancelled."""
    allowed = {"pending", "paid", "overdue", "cancelled"}
    status = new_status.strip().lower()
    if status not in allowed:
        return {"success": False, "error": f"Status must be one of: {', '.join(sorted(allowed))}"}
    def mutate(db: Session):
        invoice = db.query(models.Invoice).filter(
            models.Invoice.invoice_number == invoice_number.strip()
        ).first()
        if not invoice:
            return {"success": False, "error": f"Invoice not found: {invoice_number}"}
        old = invoice.status
        invoice.status = status
        return {
            "success": True,
            "invoice_number": invoice.invoice_number,
            "old_status": old,
            "new_status": status,
            "erp_updated": True,
        }
    return _with_db_write(mutate)


@tool
def list_invoices(client_name: str = "", status: str = "") -> list:
    """List invoices. Optionally filter by client name or status (pending/paid/overdue/cancelled)."""
    def query(db: Session):
        q = (
            db.query(models.Invoice)
            .options(joinedload(models.Invoice.client))
            .order_by(models.Invoice.due_date.desc())
        )
        if client_name.strip():
            q = q.join(models.Client).filter(models.Client.name.ilike(f"%{client_name.strip()}%"))
        if status.strip():
            q = q.filter(models.Invoice.status == status.strip().lower())
        return [
            {
                "invoice_number": inv.invoice_number,
                "client": inv.client.name if inv.client else None,
                "amount": inv.amount,
                "status": inv.status,
                "issued_date": str(inv.issued_date),
                "due_date": str(inv.due_date),
            }
            for inv in q.limit(50).all()
        ]
    return _with_db(query)


# ── Employees ─────────────────────────────────────────────────────────────────

@tool
def list_employees(department: str = "") -> list:
    """List all employees. Optionally filter by department name."""
    def query(db: Session):
        q = (
            db.query(models.Employee)
            .options(joinedload(models.Employee.department))
            .order_by(models.Employee.name)
        )
        if department.strip():
            q = q.join(models.Department).filter(models.Department.name.ilike(f"%{department.strip()}%"))
        return [
            {
                "id": e.id,
                "name": e.name,
                "email": e.email,
                "role": e.role,
                "status": e.status,
                "salary": e.salary,
                "department": e.department.name if e.department else None,
            }
            for e in q.all()
        ]
    return _with_db(query)


database_tools = [
    # Orders
    get_order_metrics,
    list_orders,
    get_client_orders,
    get_order_details,
    place_product_order,
    add_order_line_item,
    remove_order_line_item,
    remove_order,
    update_order_status,
    bulk_update_order_status,
    # Inventory / Stock
    check_product_stock,
    replenish_stock,
    update_inventory_record,
    get_inventory_summary,
    # Products
    create_product,
    list_products,
    update_product,
    delete_product,
    # Purchase Orders
    create_supplier_purchase_order,
    get_purchase_order_details,
    receive_supplier_purchase_order,
    # Clients
    add_client,
    update_client,
    remove_client,
    list_clients,
    # Suppliers
    add_supplier,
    update_supplier,
    remove_supplier,
    list_suppliers,
    # Machines
    add_machine,
    update_machine,
    remove_machine,
    get_machine_info,
    get_all_machines,
    # Maintenance
    list_maintenance_logs,
    add_maintenance_log,
    update_maintenance_log,
    # Invoices
    create_invoice,
    update_invoice_status,
    list_invoices,
    get_invoice_summary,
    # Employees
    add_employee_record,
    update_employee_salary,
    remove_employee_record,
    list_employees,
    # Manuals / RAG
    search_machine_manual,
]
