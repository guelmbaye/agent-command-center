"""acc-mock-enterprise — simulated ERP, suppliers and procurement.

Deterministic by construction: the failure is triggered by an operator, never
by chance. That is what makes the demo replayable ten times out of ten.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from mock_enterprise.state import STATE

app = FastAPI(title="ACC — Mock Enterprise Systems", version="0.1.0")


# ---------------------------------------------------------------------------
# Fournisseurs
# ---------------------------------------------------------------------------
@app.get("/suppliers/{supplier_id}")
async def get_supplier(supplier_id: str) -> Any:
    supplier = STATE.suppliers.get(supplier_id.upper())
    if supplier is None:
        raise HTTPException(status_code=404, detail=f"Unknown supplier: {supplier_id}")
    if supplier.failing:
        # Panne d'infrastructure realiste : 503 Service Unavailable.
        return JSONResponse(
            status_code=503,
            content={"error": "SUPPLIER_SYSTEM_UNAVAILABLE",
                     "supplier_id": supplier.supplier_id,
                     "detail": "The supplier system is not responding"},
        )
    return supplier.to_public()


@app.get("/suppliers")
async def list_suppliers(
    exclude: str = Query(default=""), min_units: int = Query(default=0)
) -> dict:
    excluded = {s.strip().upper() for s in exclude.split(",") if s.strip()}
    items = [
        s.to_public() for s in STATE.suppliers.values()
        if s.supplier_id not in excluded and not s.failing
        and s.capacity_units >= min_units
    ]
    return {"suppliers": items, "count": len(items)}


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------
@app.get("/production/schedule")
async def production_schedule() -> dict:
    return STATE.production_schedule


# ---------------------------------------------------------------------------
# Risque
# ---------------------------------------------------------------------------
@app.post("/risk/assess")
async def assess_risk(payload: dict) -> dict:
    supplier_id = str(payload.get("supplier_id", "")).upper()
    supplier = STATE.suppliers.get(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail=f"Unknown supplier: {supplier_id}")

    required = int(payload.get("required_units", 0) or 0)
    deadline = float(payload.get("deadline_hours", 48) or 48)
    within_deadline = supplier.lead_time_hours <= deadline
    enough = supplier.capacity_units >= required

    factors = list(supplier.risk_factors)
    if not within_deadline:
        factors.append(
            f"Lead time {supplier.lead_time_hours:g}h exceeds the {deadline:g}h deadline"
        )
    if not enough:
        factors.append(f"Capacity {supplier.capacity_units} < {required} required")

    risk_level = supplier.risk_level
    if not within_deadline or not enough:
        risk_level = "HIGH"

    return {
        "supplier_id": supplier.supplier_id,
        "risk_level": risk_level,
        "risk_factors": factors,
        "continuity_impact": "LOW" if (within_deadline and enough) else "HIGH",
        "lead_time_hours": supplier.lead_time_hours,
        "capacity_units": supplier.capacity_units,
        "within_deadline": within_deadline,
        "unit_price": supplier.unit_price,
    }


# ---------------------------------------------------------------------------
# Achats
# ---------------------------------------------------------------------------
@app.post("/procurement/purchase")
async def purchase(payload: dict) -> dict:
    supplier_id = str(payload.get("supplier_id", "")).upper()
    supplier = STATE.suppliers.get(supplier_id)
    if supplier is None or supplier.failing:
        raise HTTPException(status_code=503, detail="Procurement system unavailable")

    units = int(payload.get("units", 0) or 0)
    amount = float(payload.get("amount", 0) or 0)
    STATE.purchase_counter += 1
    purchase_id = f"PO-{STATE.purchase_counter}"
    record = {
        "purchase_id": purchase_id,
        "supplier_id": supplier.supplier_id,
        "units": units,
        "amount": amount,
        "status": "CONFIRMED",
        "eta_hours": supplier.lead_time_hours,
    }
    STATE.purchases[purchase_id] = record
    return record


@app.get("/procurement/purchases")
async def list_purchases() -> dict:
    return {"purchases": list(STATE.purchases.values()),
            "count": len(STATE.purchases)}


# ---------------------------------------------------------------------------
# Controles de demonstration
# ---------------------------------------------------------------------------
@app.post("/demo/suppliers/{supplier_id}/fail")
async def fail_supplier(supplier_id: str) -> dict:
    supplier = STATE.suppliers[supplier_id.upper()]
    supplier.failing = True
    supplier.status = "UNAVAILABLE"
    supplier.capacity_pct = 0
    return {"supplier_id": supplier.supplier_id, "failing": True}


@app.post("/demo/suppliers/{supplier_id}/restore")
async def restore_supplier(supplier_id: str) -> dict:
    supplier = STATE.suppliers[supplier_id.upper()]
    supplier.failing = False
    supplier.status = "AVAILABLE"
    supplier.capacity_pct = 100
    return {"supplier_id": supplier.supplier_id, "failing": False}


@app.post("/demo/suppliers/{supplier_id}/poison")
async def poison_supplier(supplier_id: str) -> dict:
    supplier = STATE.suppliers[supplier_id.upper()]
    supplier.poisoned = True
    return {"supplier_id": supplier.supplier_id, "poisoned": True}


@app.post("/demo/suppliers/{supplier_id}/clean")
async def clean_supplier(supplier_id: str) -> dict:
    supplier = STATE.suppliers[supplier_id.upper()]
    supplier.poisoned = False
    return {"supplier_id": supplier.supplier_id, "poisoned": False}


@app.post("/demo/reset")
async def reset() -> dict:
    STATE.reset()
    return {"reset": True}


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "suppliers": len(STATE.suppliers)}
