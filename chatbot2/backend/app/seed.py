from datetime import date, datetime
from sqlalchemy.orm import Session
from .database import engine, SessionLocal, Base
from . import models
from .db_migrate import migrate_schema


def seed_database(db: Session) -> None:
    if db.query(models.Client).count() > 0:
        return

    departments = [
        models.Department(name="Production", code="PROD"),
        models.Department(name="Sales", code="SALES"),
        models.Department(name="Maintenance", code="MAINT"),
        models.Department(name="Procurement", code="PROC"),
    ]
    db.add_all(departments)
    db.flush()

    employees = [
        models.Employee(name="Sarah Chen", email="sarah@factory.com", role="Plant Manager", status="active", salary=95000.0, department_id=departments[0].id),
        models.Employee(name="Mike Johnson", email="mike@factory.com", role="Maintenance Lead", status="active", salary=72000.0, department_id=departments[2].id),
        models.Employee(name="Lisa Park", email="lisa@factory.com", role="Sales Director", status="active", salary=88000.0, department_id=departments[1].id),
        models.Employee(name="Tom Rivera", email="tom@factory.com", role="CNC Operator", status="active", salary=58000.0, department_id=departments[0].id),
    ]
    db.add_all(employees)
    db.flush()

    suppliers = [
        models.Supplier(name="SteelWorks Ltd", email="orders@steelworks.com", phone="+1-555-0101", company="SteelWorks Ltd"),
        models.Supplier(name="Precision Tools Co", email="sales@ptools.com", phone="+1-555-0102", company="Precision Tools Co"),
        models.Supplier(name="Industrial Bearings Inc", email="info@ibearings.com", phone="+1-555-0103", company="Industrial Bearings Inc"),
    ]
    db.add_all(suppliers)
    db.flush()

    clients = [
        models.Client(name="Acme Corp", email="contact@acme.com", company="Acme Industries", phone="+1-555-1001"),
        models.Client(name="TechFlow Inc", email="sales@techflow.com", company="TechFlow Inc", phone="+1-555-1002"),
        models.Client(name="Global Manufacturing", email="info@globalmfg.com", company="Global Manufacturing LLC", phone="+1-555-1003"),
        models.Client(name="Nova Automotive", email="procurement@novaauto.com", company="Nova Automotive", phone="+1-555-1004"),
    ]
    db.add_all(clients)
    db.flush()

    products = [
        models.Product(sku="PRD-001", name="Steel Bracket Assembly", category="Components", unit_price=45.0, stock_qty=320, reorder_level=50),
        models.Product(sku="PRD-002", name="Aluminum Housing", category="Components", unit_price=78.5, stock_qty=180, reorder_level=40),
        models.Product(sku="PRD-003", name="Precision Shaft", category="Machined Parts", unit_price=120.0, stock_qty=95, reorder_level=25),
        models.Product(sku="PRD-004", name="Control Panel Unit", category="Electronics", unit_price=250.0, stock_qty=42, reorder_level=15),
        models.Product(sku="PRD-005", name="Hydraulic Cylinder", category="Hydraulics", unit_price=310.0, stock_qty=28, reorder_level=10),
        models.Product(sku="PRD-006", name="Bearing Set 6205", category="Spare Parts", unit_price=22.0, stock_qty=8, reorder_level=30),
    ]
    db.add_all(products)
    db.flush()

    machines = [
        models.Machine(name="CNC Alpha-1", type="CNC", status="Running", efficiency=92.5, location="Zone A", serial_number="CNC-A1-2022", manual_file="CNC_Alpha-1_Manual.pdf", installed_date=date(2022, 3, 15)),
        models.Machine(name="CNC Bravo-2", type="CNC", status="Maintenance", efficiency=0.0, location="Zone A", serial_number="CNC-B2-2021", manual_file="CNC_Bravo-2_Manual.pdf", installed_date=date(2021, 8, 10)),
        models.Machine(name="VMC Pro-5", type="VMC", status="Running", efficiency=88.0, location="Zone B", serial_number="VMC-P5-2023", manual_file="VMC_Pro-5_Manual.pdf", installed_date=date(2023, 1, 20)),
        models.Machine(name="VMC Lite-1", type="VMC", status="Idle", efficiency=100.0, location="Zone B", serial_number="VMC-L1-2020", manual_file="VMC_Lite-1_Manual.pdf", installed_date=date(2020, 11, 5)),
        models.Machine(name="Lathe X-90", type="Lathe", status="Running", efficiency=75.5, location="Zone C", serial_number="LAT-X90-2019", manual_file="Lathe_X-90_Manual.pdf", installed_date=date(2019, 6, 12)),
    ]
    db.add_all(machines)
    db.flush()

    orders_data = [
        ("Order-1001", clients[0].id, "completed", 12500.0, date(2025, 11, 2)),
        ("Order-1002", clients[0].id, "ongoing", 4500.5, date(2026, 1, 15)),
        ("Order-1003", clients[1].id, "pending", 8900.0, date(2026, 2, 1)),
        ("Order-1004", clients[2].id, "ongoing", 22000.0, date(2026, 1, 28)),
        ("Order-1005", clients[1].id, "completed", 1500.0, date(2025, 12, 10)),
        ("Order-1006", clients[3].id, "pending", 18750.0, date(2026, 3, 5)),
    ]
    orders = []
    for oname, cid, status, total, odate in orders_data:
        o = models.Order(order_name=oname, client_id=cid, status=status, total_amount=total, order_date=odate)
        orders.append(o)
        db.add(o)
    db.flush()

    order_items = [
        models.OrderItem(order_id=orders[0].id, product_id=products[0].id, quantity=100, unit_price=45.0),
        models.OrderItem(order_id=orders[0].id, product_id=products[2].id, quantity=50, unit_price=120.0),
        models.OrderItem(order_id=orders[1].id, product_id=products[1].id, quantity=40, unit_price=78.5),
        models.OrderItem(order_id=orders[2].id, product_id=products[3].id, quantity=30, unit_price=250.0),
        models.OrderItem(order_id=orders[3].id, product_id=products[4].id, quantity=60, unit_price=310.0),
        models.OrderItem(order_id=orders[4].id, product_id=products[5].id, quantity=50, unit_price=22.0),
        models.OrderItem(order_id=orders[5].id, product_id=products[0].id, quantity=200, unit_price=45.0),
        models.OrderItem(order_id=orders[5].id, product_id=products[2].id, quantity=50, unit_price=75.0),
    ]
    db.add_all(order_items)

    pos = [
        models.PurchaseOrder(po_number="PO-5001", supplier_id=suppliers[0].id, status="received", total_amount=8500.0, order_date=date(2026, 1, 5)),
        models.PurchaseOrder(po_number="PO-5002", supplier_id=suppliers[1].id, status="pending", total_amount=3200.0, order_date=date(2026, 2, 18)),
        models.PurchaseOrder(po_number="PO-5003", supplier_id=suppliers[2].id, status="approved", total_amount=1100.0, order_date=date(2026, 3, 1)),
    ]
    db.add_all(pos)
    db.flush()

    po_items = [
        models.PurchaseOrderItem(purchase_order_id=pos[0].id, product_id=products[0].id, quantity=150, unit_price=40.0),
        models.PurchaseOrderItem(purchase_order_id=pos[1].id, product_id=products[5].id, quantity=100, unit_price=18.0),
        models.PurchaseOrderItem(purchase_order_id=pos[2].id, product_id=products[5].id, quantity=50, unit_price=22.0),
    ]
    db.add_all(po_items)

    invoices = [
        models.Invoice(invoice_number="INV-2001", order_id=orders[0].id, client_id=clients[0].id, amount=12500.0, status="paid", due_date=date(2025, 12, 2), issued_date=date(2025, 11, 2)),
        models.Invoice(invoice_number="INV-2002", order_id=orders[1].id, client_id=clients[0].id, amount=4500.5, status="pending", due_date=date(2026, 3, 15), issued_date=date(2026, 1, 15)),
        models.Invoice(invoice_number="INV-2003", order_id=orders[4].id, client_id=clients[1].id, amount=1500.0, status="paid", due_date=date(2026, 1, 10), issued_date=date(2025, 12, 10)),
        models.Invoice(invoice_number="INV-2004", order_id=orders[3].id, client_id=clients[2].id, amount=22000.0, status="overdue", due_date=date(2026, 2, 28), issued_date=date(2026, 1, 28)),
    ]
    db.add_all(invoices)

    maintenance = [
        models.MaintenanceLog(machine_id=machines[1].id, technician_id=employees[1].id, maintenance_type="Preventive", description="Spindle bearing replacement and lubrication", scheduled_date=date(2026, 3, 10), completed_date=None, status="scheduled"),
        models.MaintenanceLog(machine_id=machines[0].id, technician_id=employees[1].id, maintenance_type="Inspection", description="Quarterly safety and calibration check", scheduled_date=date(2026, 2, 15), completed_date=date(2026, 2, 15), status="completed"),
        models.MaintenanceLog(machine_id=machines[4].id, technician_id=employees[3].id, maintenance_type="Corrective", description="Tool post alignment adjustment", scheduled_date=date(2026, 1, 20), completed_date=date(2026, 1, 21), status="completed"),
    ]
    db.add_all(maintenance)

    movements = [
        models.InventoryMovement(product_id=products[0].id, movement_type="in", quantity=150, reference="PO-5001", notes="Steel bracket restock"),
        models.InventoryMovement(product_id=products[5].id, movement_type="out", quantity=42, reference="Order-1005", notes="Shipped to TechFlow"),
        models.InventoryMovement(product_id=products[3].id, movement_type="out", quantity=8, reference="Order-1003", notes="Allocated for pending order"),
    ]
    db.add_all(movements)
    db.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
