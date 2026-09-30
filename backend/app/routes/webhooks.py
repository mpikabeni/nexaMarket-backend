from fastapi import APIRouter, Request
router=APIRouter(prefix="/webhooks",tags=["Webhooks"])
@router.post("/jessikapay")
async def jessikapay_webhook(request: Request):
    payload=await request.json(); event=payload.get("event")
    # Les documents fournis ne définissent pas de signature entrante : aucune signature inventée ici.
    # Le traitement financier doit être idempotent par reference/request_id dans les services.
    return {"received":True,"event":event}
