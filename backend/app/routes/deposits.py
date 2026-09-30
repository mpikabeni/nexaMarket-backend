from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.deposit import Deposit
from app.services.jessikapay_service import jessikapay_service, JessiKaPayError
from uuid import uuid4
router=APIRouter(prefix="/deposits",tags=["Deposits"])
@router.post("")
async def create_deposit(payload: dict, db: AsyncSession=Depends(get_db), user: User=Depends(get_current_user)):
    amount=float(payload.get("amount",0)); phone=str(payload.get("phone","")).strip(); country=str(payload.get("country","CG")).upper()
    if amount<=0 or not phone: raise HTTPException(400,"Montant et numéro de paiement requis")
    reference="DEP-"+uuid4().hex[:20].upper()
    try: provider=await jessikapay_service.create_deposit({"telegram_id":str(user.telegram_id),"name":user.first_name or user.username or "NexMarket","country":country,"phone":phone,"amount":amount,"reference":reference})
    except JessiKaPayError as e: raise HTTPException(502,str(e))
    dep=Deposit(user_id=user.id,reference=reference,amount=amount,currency="XAF",country=country,phone=phone,jessikapay_request_id=str(provider.get("request_id")),jessikapay_code=provider.get("code"),payment_link=provider.get("payment_link"),status=provider.get("status","pending"),expires_at=None)
    db.add(dep); await db.commit(); await db.refresh(dep)
    return {"id":dep.id,"reference":dep.reference,"amount":float(dep.amount),"status":dep.status,"payment_link":dep.payment_link,"code":dep.jessikapay_code}
@router.get("/mine")
async def my_deposits(db: AsyncSession=Depends(get_db), user: User=Depends(get_current_user)):
    from sqlalchemy import select
    rows=(await db.execute(select(Deposit).where(Deposit.user_id==user.id).order_by(Deposit.created_at.desc()))).scalars().all()
    return [{"id":d.id,"reference":d.reference,"amount":float(d.amount),"status":d.status,"created_at":d.created_at.isoformat()} for d in rows]
