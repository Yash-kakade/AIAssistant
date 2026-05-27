from datetime import date, datetime
from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DashboardStats(BaseModel):
    total_orders: int
    pending_orders: int
    ongoing_orders: int
    completed_orders: int
    total_clients: int
    total_products: int
    low_stock_products: int
    running_machines: int
    machines_in_maintenance: int
    total_revenue: float
    pending_invoices: int


class ClientOut(ORMBase):
    id: int
    name: str
    email: str | None
    company: str | None
    phone: str | None


class ProductOut(ORMBase):
    id: int
    sku: str
    name: str
    category: str
    unit_price: float
    stock_qty: int
    reorder_level: int


class MachineOut(ORMBase):
    id: int
    name: str
    type: str
    status: str
    efficiency: float
    location: str | None
    serial_number: str | None
    manual_file: str | None
    installed_date: date | None


class OrderItemOut(ORMBase):
    id: int
    product_id: int
    quantity: int
    unit_price: float
    product_name: str | None = None
    product_sku: str | None = None


class OrderOut(ORMBase):
    id: int
    order_name: str
    client_id: int
    client_name: str | None = None
    status: str
    total_amount: float
    order_date: date
    notes: str | None = None
    items: list[OrderItemOut] = []


class SupplierOut(ORMBase):
    id: int
    name: str
    email: str | None
    phone: str | None
    company: str | None


class EmployeeOut(ORMBase):
    id: int
    name: str
    email: str
    role: str
    status: str
    salary: float
    department_name: str | None = None


class InvoiceOut(ORMBase):
    id: int
    invoice_number: str
    order_id: int | None
    client_id: int
    client_name: str | None = None
    amount: float
    status: str
    due_date: date
    issued_date: date


class PurchaseOrderOut(ORMBase):
    id: int
    po_number: str
    supplier_id: int
    supplier_name: str | None = None
    status: str
    total_amount: float
    order_date: date


class MaintenanceLogOut(ORMBase):
    id: int
    machine_id: int
    machine_name: str | None = None
    technician_id: int | None
    technician_name: str | None = None
    maintenance_type: str
    description: str
    scheduled_date: date
    completed_date: date | None
    status: str


class InventoryMovementOut(ORMBase):
    id: int
    product_id: int
    product_name: str | None = None
    movement_type: str
    quantity: int
    reference: str | None
    notes: str | None
    created_at: datetime
