from sqlalchemy.orm import Session

from .. import models


def find_employee(db: Session, name_or_email: str) -> models.Employee | None:
    term = name_or_email.strip()
    emp = db.query(models.Employee).filter(models.Employee.email.ilike(term)).first()
    if emp:
        return emp
    return db.query(models.Employee).filter(models.Employee.name.ilike(f"%{term}%")).first()


def add_employee(
    db: Session,
    name: str,
    email: str,
    role: str,
    salary: float,
    department_name: str = "",
) -> dict:
    if db.query(models.Employee).filter(models.Employee.email == email).first():
        raise ValueError(f"Employee with email {email} already exists")

    department_id = None
    if department_name.strip():
        dept = (
            db.query(models.Department)
            .filter(models.Department.name.ilike(f"%{department_name.strip()}%"))
            .first()
        )
        if not dept:
            raise ValueError(f"Department not found: {department_name}")
        department_id = dept.id

    emp = models.Employee(
        name=name.strip(),
        email=email.strip(),
        role=role.strip(),
        salary=float(salary),
        status="active",
        department_id=department_id,
    )
    db.add(emp)
    db.flush()
    return {
        "success": True,
        "id": emp.id,
        "name": emp.name,
        "email": emp.email,
        "role": emp.role,
        "salary": emp.salary,
        "department_id": emp.department_id,
        "erp_updated": True,
    }


def update_employee_salary(
    db: Session,
    employee_name_or_email: str,
    new_salary: float,
    increase_by: float | None = None,
) -> dict:
    emp = find_employee(db, employee_name_or_email)
    if not emp:
        raise ValueError(f"Employee not found: {employee_name_or_email}")

    old_salary = emp.salary or 0.0
    if increase_by is not None:
        emp.salary = old_salary + float(increase_by)
    else:
        emp.salary = float(new_salary)

    return {
        "success": True,
        "name": emp.name,
        "old_salary": old_salary,
        "new_salary": emp.salary,
        "erp_updated": True,
    }


def remove_employee(db: Session, employee_name_or_email: str) -> dict:
    emp = find_employee(db, employee_name_or_email)
    if not emp:
        raise ValueError(f"Employee not found: {employee_name_or_email}")

    name = emp.name
    db.delete(emp)
    return {"success": True, "removed_employee": name, "erp_updated": True}
