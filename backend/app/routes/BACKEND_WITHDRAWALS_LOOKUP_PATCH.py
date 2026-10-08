# À ajouter dans app/routes/withdrawals.py

@router.get("/lookup/{jp_number}")
async def lookup_jp(
    jp_number: str,
    user: User = Depends(get_current_user),
):
    """Vérifie directement un compte JessiKaPay sans choisir de pays."""
    jp_number = jp_number.strip().upper()

    import re
    if not re.fullmatch(r"JP-\d{6}", jp_number):
        raise HTTPException(
            status_code=400,
            detail="Le numéro JessiKaPay doit être au format JP-222222.",
        )

    try:
        result = await jessikapay_service.lookup_jp(jp_number)
    except JessiKaPayError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Erreur JessiKaPay : {exc}",
        ) from exc

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=502,
            detail="Réponse JessiKaPay invalide.",
        )

    if not result.get("found"):
        return {"found": False}

    return {
        "found": True,
        "jp_number": result.get("jp_number") or jp_number,
        "name": result.get("name") or "",
        "first_name": result.get("first_name") or "",
        "last_name": result.get("last_name") or "",
        "photo_url": result.get("photo_url") or "",
    }
