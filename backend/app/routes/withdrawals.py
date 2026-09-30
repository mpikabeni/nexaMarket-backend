from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import get_current_user, get_current_admin
from app.models.user import User
from app.models.withdrawal import Withdrawal
from uuid import uuid4
router=APIRouter(prefix="/withdrawals",tags=["Withdrawals"])
@router.post("")
async def request_withdrawal(payload: dict, db: AsyncSession=Depends(get_db), user: User=Depends(get_current_user)):
    amount=float(payload.get("amount",0)); jp=str(payload.get("jp_number","")).strip()
    if amount<=0 or not jp: raise HTTPException(400,"Montant et numéro JessiKaPay requis")
    from app.services.wallet_service import WalletService
    ws=WalletService(db); wallet=await ws.get_wallet(user.id)
    if float(wallet.available_balance)<amount: raise HTTPException(400,"Solde insuffisant")
    await ws.block(user.id, amount, "WD-"+uuid4().hex[:16].upper())
    w=Withdrawal(user_id=user.id,reference="WD-"+uuid4().hex[:16].upper(),amount=amount,currency="XAF",jessikapay_jp_number=jp,status="pending")
    db.add(w); await db.commit(); await db.refresh(w)
    return {"id":w.id,"reference":w.reference,"amount":float(w.amount),"status":w.status}
@router.get("/mine")
async def mine(db: AsyncSession=Depends(get_db), user: User=Depends(get_current_user)):
    from sqlalchemy import select
    rows=(await db.execute(select(Withdrawal).where(Withdrawal.user_id==user.id).order_by(Withdrawal.created_at.desc()))).scalars().all()
    return [{"id":w.id,"reference":w.reference,"amount":float(w.amount),"status":w.status,"created_at":w.created_at.isoformat()} for w in rows]
