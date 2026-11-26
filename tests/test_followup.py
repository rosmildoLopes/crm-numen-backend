from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from app.main import lead_access
from app.security import can
from fastapi import HTTPException

def test_seller_has_lead_read_permission():
    seller=SimpleNamespace(id=7,role='vendedor')
    assert can(seller,'leads.read')
    lead_access(SimpleNamespace(assigned_to_id=7),seller)

def test_seller_cannot_read_other_leads():
    seller=SimpleNamespace(id=7,role='vendedor')
    try:
        lead_access(SimpleNamespace(assigned_to_id=8),seller)
        assert False, 'Expected 403'
    except HTTPException as exc:
        assert exc.status_code==403
