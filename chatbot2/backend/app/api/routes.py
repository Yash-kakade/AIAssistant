from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import case, func

from ..database import get_db
from .. import models
from ..services.order_service import add_line_item
from ..schemas import (
    DashboardStats, ClientOut, ProductOut, MachineOut, OrderOut, OrderItemOut,
    SupplierOut, EmployeeOut, InvoiceOut, PurchaseOrderOut, MaintenanceLogOut,
    InventoryMovementOut,
)

router = APIRouter(prefix="/api")


@router.get("/dashboard", response_model=DashboardStats)
def get_dashboard(db: Session = Depends(get_db)):
    # Consolidate 9 separate scalar queries into 2 queries using CASE/WHEN
    # aggregations — reduces SQLite round-trips significantly.
    order_row = db.query(
        func.count(models.Order.id).label("total"),
        func.sum(case((models.Order.status == "pending", 1), else_=0)).label("pending"),
        func.sum(case((models.Order.status == "ongoing", 1), else_=0)).label("ongoing"),
        func.sum(case((models.Order.status == "completed", 1), else_=0)).label("completed"),
    ).one()

    product_row = db.query(
        func.count(models.Product.id).label("total"),
        func.sum(case((models.Product.stock_qty < models.Product.reorder_level, 1), else_=0)).label("low_stock"),
    ).one()

    machine_row = db.query(
        func.sum(case((models.Machine.status == "Running", 1), else_=0)).label("running"),
        func.sum(case((models.Machine.status == "Maintenance", 1), else_=0)).label("maintenance"),
    ).one()

    invoice_row = db.query(
        func.coalesce(func.sum(case((models.Invoice.status == "paid", models.Invoice.amount), else_=0)), 0).label("revenue"),
        func.sum(case((models.Invoice.status.in_(["pending", "overdue"]), 1), else_=0)).label("pending_count"),
    ).one()

    total_clients = db.query(func.count(models.Client.id)).scalar() or 0

    return DashboardStats(
        total_orders=order_row.total or 0,
        pending_orders=order_row.pending or 0,
        ongoing_orders=order_row.ongoing or 0,
        completed_orders=order_row.completed or 0,
        total_clients=total_clients,
        total_products=product_row.total or 0,
        low_stock_products=product_row.low_stock or 0,
        running_machines=machine_row.running or 0,
        machines_in_maintenance=machine_row.maintenance or 0,
        total_revenue=float(invoice_row.revenue or 0),
        pending_invoices=invoice_row.pending_count or 0,
    )


@router.get("/clients", response_model=list[ClientOut])
def list_clients(db: Session = Depends(get_db)):
    return db.query(models.Client).order_by(models.Client.name).all()


@router.get("/clients/{client_id}", response_model=ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db)):
    client = db.get(models.Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return client


@router.get("/products", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(models.Product).order_by(models.Product.name).all()


@router.get("/products/low-stock", response_model=list[ProductOut])
def list_low_stock(db: Session = Depends(get_db)):
    return (
        db.query(models.Product)
        .filter(models.Product.stock_qty < models.Product.reorder_level)
        .order_by(models.Product.stock_qty)
        .all()
    )


@router.get("/machines", response_model=list[MachineOut])
def list_machines(db: Session = Depends(get_db)):
    return db.query(models.Machine).order_by(models.Machine.name).all()


@router.get("/machines/{machine_id}", response_model=MachineOut)
def get_machine(machine_id: int, db: Session = Depends(get_db)):
    machine = db.get(models.Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    return machine


@router.get("/orders", response_model=list[OrderOut])
def list_orders(db: Session = Depends(get_db)):
    orders = (
        db.query(models.Order)
        .options(joinedload(models.Order.client), joinedload(models.Order.items).joinedload(models.OrderItem.product))
        .order_by(models.Order.order_date.desc())
        .all()
    )
    return [_serialize_order(o) for o in orders]


class AddOrderItemBody(BaseModel):
    product_name_or_sku: str
    quantity: int = Field(gt=0)


@router.post("/orders/by-name/{order_name}/items")
def add_order_item_api(order_name: str, body: AddOrderItemBody, db: Session = Depends(get_db)):
    try:
        result = add_line_item(db, order_name, body.product_name_or_sku, body.quantity)
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = (
        db.query(models.Order)
        .options(joinedload(models.Order.client), joinedload(models.Order.items).joinedload(models.OrderItem.product))
        .filter(models.Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(404, "Order not found")
    return _serialize_order(order)


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)):
    return db.query(models.Supplier).order_by(models.Supplier.name).all()


@router.get("/employees", response_model=list[EmployeeOut])
def list_employees(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Employee)
        .options(joinedload(models.Employee.department))
        .order_by(models.Employee.name)
        .all()
    )
    return [
        EmployeeOut(
            id=e.id, name=e.name, email=e.email, role=e.role, status=e.status,
            salary=e.salary or 0.0,
            department_name=e.department.name if e.department else None,
        )
        for e in rows
    ]


@router.get("/invoices", response_model=list[InvoiceOut])
def list_invoices(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Invoice)
        .options(joinedload(models.Invoice.client))
        .order_by(models.Invoice.issued_date.desc())
        .all()
    )
    return [
        InvoiceOut(
            id=i.id, invoice_number=i.invoice_number, order_id=i.order_id,
            client_id=i.client_id, client_name=i.client.name if i.client else None,
            amount=i.amount, status=i.status, due_date=i.due_date, issued_date=i.issued_date,
        )
        for i in rows
    ]


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(db: Session = Depends(get_db)):
    rows = (
        db.query(models.PurchaseOrder)
        .options(joinedload(models.PurchaseOrder.supplier))
        .order_by(models.PurchaseOrder.order_date.desc())
        .all()
    )
    return [
        PurchaseOrderOut(
            id=p.id, po_number=p.po_number, supplier_id=p.supplier_id,
            supplier_name=p.supplier.name if p.supplier else None,
            status=p.status, total_amount=p.total_amount, order_date=p.order_date,
        )
        for p in rows
    ]


@router.get("/maintenance", response_model=list[MaintenanceLogOut])
def list_maintenance(db: Session = Depends(get_db)):
    rows = (
        db.query(models.MaintenanceLog)
        .options(joinedload(models.MaintenanceLog.machine), joinedload(models.MaintenanceLog.technician))
        .order_by(models.MaintenanceLog.scheduled_date.desc())
        .all()
    )
    return [
        MaintenanceLogOut(
            id=m.id, machine_id=m.machine_id,
            machine_name=m.machine.name if m.machine else None,
            technician_id=m.technician_id,
            technician_name=m.technician.name if m.technician else None,
            maintenance_type=m.maintenance_type, description=m.description,
            scheduled_date=m.scheduled_date, completed_date=m.completed_date, status=m.status,
        )
        for m in rows
    ]


@router.get("/inventory/movements", response_model=list[InventoryMovementOut])
def list_inventory_movements(db: Session = Depends(get_db)):
    rows = (
        db.query(models.InventoryMovement)
        .options(joinedload(models.InventoryMovement.product))
        .order_by(models.InventoryMovement.created_at.desc())
        .limit(200)  # Only the 200 most-recent movements; avoids unbounded growth
        .all()
    )
    return [
        InventoryMovementOut(
            id=m.id, product_id=m.product_id,
            product_name=m.product.name if m.product else None,
            movement_type=m.movement_type, quantity=m.quantity,
            reference=m.reference, notes=m.notes, created_at=m.created_at,
        )
        for m in rows
    ]


def _serialize_order(order: models.Order) -> OrderOut:
    items = [
        OrderItemOut(
            id=it.id, product_id=it.product_id, quantity=it.quantity, unit_price=it.unit_price,
            product_name=it.product.name if it.product else None,
            product_sku=it.product.sku if it.product else None,
        )
        for it in order.items
    ]
    return OrderOut(
        id=order.id, order_name=order.order_name, client_id=order.client_id,
        client_name=order.client.name if order.client else None,
        status=order.status, total_amount=order.total_amount, order_date=order.order_date,
        notes=order.notes, items=items,
    )
