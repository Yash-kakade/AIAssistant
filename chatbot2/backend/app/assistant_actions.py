import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .database import SessionLocal
from .services.order_service import (
    create_sales_order,
    get_product_stock,
    replenish_product_stock,
    update_product_inventory,
)
from .services.purchase_order_service import (
    create_purchase_order,
    receive_purchase_order,
)
from . import models


@dataclass
class DirectActionResult:
    handled: bool
    content: str = ""
    erp_changed: bool = False


def _history_text(history: list[dict[str, str]]) -> str:
    return "\n".join((item.get("content") or "") for item in history[-8:])


def _find_product_term(db: Session, message: str, history: list[dict[str, str]]) -> str | None:
    text = f"{message}\n{_history_text(history)}"
    sku_match = re.search(r"\bPRD-\d{3,}\b", text, flags=re.IGNORECASE)
    if sku_match:
        return sku_match.group(0).upper()

    products = db.query(models.Product).order_by(models.Product.id).all()
    text_lower = text.lower()
    for product in products:
        if product.name.lower() in text_lower:
            return product.sku
    return None


def _find_po_number(message: str, history: list[dict[str, str]]) -> str | None:
    text = f"{message}\n{_history_text(history)}"
    match = re.search(r"\b(?:PO|Purchase\s*Order)-?\s*(\d{3,})\b", text, flags=re.IGNORECASE)
    if match:
        return f"PO-{match.group(1)}"
    return None


def _quantity(message: str) -> int | None:
    match = re.search(r"\b(\d+)\s*(?:units?|pcs?|pieces?)?\b", message, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _wants_stock_add(message: str) -> bool:
    msg = message.lower()
    return bool(
        re.search(r"\b(add|increase|restock|replenish)\b", msg)
        and re.search(r"\b(stock|inventory|units?|pcs?|pieces?)\b", msg)
    )


def _wants_remove_low_stock_alert(message: str) -> bool:
    msg = message.lower()
    return "low stock" in msg and any(word in msg for word in ("remove", "clear", "hide", "fix"))


def _wants_create_low_stock_alert(message: str) -> bool:
    msg = message.lower()
    return "low stock" in msg and any(word in msg for word in ("create", "add", "make", "set", "show"))


def _low_stock_sentence(stock_qty: int, reorder_level: int) -> str:
    if stock_qty < reorder_level:
        return (
            f"Automatic low-stock alert is active because stock {stock_qty} "
            f"is below reorder level {reorder_level}."
        )
    return (
        f"No low-stock alert is active because stock {stock_qty} "
        f"is not below reorder level {reorder_level}."
    )


def _wants_purchase_order(message: str) -> bool:
    msg = message.lower()
    return "purchase order" in msg or bool(re.search(r"\b(create|place|add)\b.*\bpo\b", msg))


def _wants_sales_order(message: str) -> bool:
    msg = message.lower()
    if _wants_purchase_order(message):
        return False
    return bool(
        re.search(r"\b(create|make|place|add|new)\b", msg)
        and re.search(r"\border\b", msg)
    )


def _wants_receive_po(message: str) -> bool:
    msg = message.lower()
    return bool(re.search(r"\b(receive|received|confirm receipt|mark received|goods received)\b", msg))


def _format_stock(result: dict) -> str:
    return (
        f"{result['product']} ({result.get('sku', '')}) is now at "
        f"{result['new_stock_qty']} units."
    )


def try_direct_erp_action(
    message: str,
    history: list[dict[str, str]] | None = None,
) -> DirectActionResult:
    history = history or []
    db = SessionLocal()
    try:
        product_term = _find_product_term(db, message, history)

        if _wants_stock_add(message):
            qty = _quantity(message)
            if not product_term or not qty:
                return DirectActionResult(False)
            result = replenish_product_stock(db, product_term, qty)
            db.commit()
            stock = get_product_stock(db, product_term)
            return DirectActionResult(
                handled=True,
                erp_changed=True,
                content=(
                    f"Added {result['added_qty']} units to {result['product']}. "
                    f"New stock: {result['new_stock_qty']}. "
                    f"{_low_stock_sentence(stock['stock_qty'], stock['reorder_level'])}"
                ),
            )

        if _wants_remove_low_stock_alert(message):
            if not product_term:
                return DirectActionResult(False)
            stock = get_product_stock(db, product_term)
            if not stock.get("success"):
                return DirectActionResult(True, stock.get("error", "Product not found."), False)
            target_stock = max(stock["stock_qty"], stock["reorder_level"])
            if target_stock == stock["stock_qty"]:
                return DirectActionResult(
                    handled=True,
                    erp_changed=False,
                    content=(
                        f"{stock['name']} is already not low stock: "
                        f"{stock['stock_qty']} on hand, reorder level {stock['reorder_level']}."
                    ),
                )
            result = update_product_inventory(db, product_term, stock_qty=target_stock)
            db.commit()
            return DirectActionResult(
                handled=True,
                erp_changed=True,
                content=(
                    f"Cleared the low stock alert for {result['product']}. "
                    f"Stock is now {result['new_stock_qty']} and reorder level is "
                    f"{result['new_reorder_level']}."
                ),
            )

        if _wants_create_low_stock_alert(message):
            if not product_term:
                return DirectActionResult(False)
            stock = get_product_stock(db, product_term)
            if not stock.get("success"):
                return DirectActionResult(True, stock.get("error", "Product not found."), False)
            return DirectActionResult(
                handled=True,
                erp_changed=False,
                content=(
                    f"Low-stock alerts are automatic. {stock['name']} has "
                    f"{stock['stock_qty']} on hand and reorder level {stock['reorder_level']}. "
                    f"{_low_stock_sentence(stock['stock_qty'], stock['reorder_level'])}"
                ),
            )

        if _wants_purchase_order(message):
            qty = _quantity(message)
            if not product_term or not qty:
                return DirectActionResult(False)
            result = create_purchase_order(db, product_term, qty)
            db.commit()
            return DirectActionResult(
                handled=True,
                erp_changed=True,
                content=(
                    f"Created purchase order {result['po_number']} for {result['quantity']} "
                    f"units of {result['product']} from {result['supplier_name']}. "
                    f"Status: {result['status']}."
                ),
            )

        if _wants_sales_order(message):
            qty = _quantity(message)
            if not product_term or not qty:
                return DirectActionResult(False)
            result = create_sales_order(db, "", product_term, qty)
            db.commit()
            stock = get_product_stock(db, product_term)
            return DirectActionResult(
                handled=True,
                erp_changed=True,
                content=(
                    f"Created sales order {result['order_name']} for {result['quantity_added']} "
                    f"units of {result['product']} for {result['client_name']}. "
                    f"Order total: ${result['new_order_total']:.2f}. "
                    f"Remaining stock: {result['remaining_stock']}. "
                    f"{_low_stock_sentence(stock['stock_qty'], stock['reorder_level'])}"
                ),
            )

        if _wants_receive_po(message):
            po_number = _find_po_number(message, history)
            if not po_number:
                return DirectActionResult(False)
            result = receive_purchase_order(db, po_number)
            db.commit()
            if not result.get("erp_updated"):
                return DirectActionResult(True, result.get("message", f"{po_number} was already received."), False)
            items = ", ".join(
                f"{item['quantity_received']} {item['product']} (stock {item['new_stock_qty']})"
                for item in result["received_items"]
            )
            return DirectActionResult(
                handled=True,
                erp_changed=True,
                content=f"Received {result['po_number']} and updated inventory: {items}.",
            )

        return DirectActionResult(False)
    except Exception as e:
        db.rollback()
        return DirectActionResult(True, f"Could not complete that ERP change: {e}", False)
    finally:
        db.close()
