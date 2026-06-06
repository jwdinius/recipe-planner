from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from app.db import get_session

router = APIRouter()


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    try:
        result = session.execute(text("SELECT 1")).scalar()
        db_ok = result == 1
    except Exception:
        db_ok = False
    return {"status": "ok", "db_ok": db_ok}
