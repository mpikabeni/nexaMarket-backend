# Déploiement sur Render — checklist (v31)

## 1. Avant de déployer
- [ ] Code poussé sur GitHub (backend à la racine du dépôt : `Dockerfile`, `render.yaml`, `app/`).
- [ ] Frontend (Netlify/Vercel) à jour ; `FRONTEND_URL` et `CORS_ORIGINS` = son adresse exacte.
- [ ] Compte MoneyFusion avec une **application** dont l'URL de site = `FRONTEND_URL`.

## 2. Créer le service
1. Render → **New → Blueprint** → choisissez le dépôt (lit `render.yaml`).
2. Remplissez les variables marquées « à saisir » (voir §3), puis **Apply**.
3. **Offre payante recommandée** pour le service ET la base : en gratuit, le service s'endort
   (le bot et les tâches de fond s'arrêtent) et la base gratuite est supprimée après un délai.
   Ne mettez jamais de vrais paiements sur la base gratuite.

## 3. Variables à saisir
| Variable | Où la trouver |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` | @BotFather |
| `ADMIN_CODE`, `ADMIN_TELEGRAM_ID` | à vous (votre ID Telegram numérique) |
| `MONEYFUSION_API_URL` | tableau de bord MoneyFusion → votre application → lien d'API |
| `MONEYFUSION_PRIVATE_KEY` | tableau de bord MoneyFusion → clé privée (retraits) |
| `NEXA_PAYOUT_COUNTRY / METHOD / PHONE` | compte Mobile Money qui reçoit vos commissions (ex. `cg`, `mtn-cg`, numéro) |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | console.groq.com / aistudio.google.com (au moins une) |
| `MONEYFUSION_FX_TO_XAF` | optionnel : devises non CFA, ex. `{"GNF":0.07}` |

`MONEYFUSION_WEBHOOK_SECRET` et `JWT_SECRET` sont générés par Render.

## 4. IP fixe à donner à MoneyFusion (obligatoire)
1. Service Render → bouton **Connect** (en haut à droite) → onglet **Outbound**.
2. Copiez **toutes** les adresses/plages listées et enregistrez-les chez MoneyFusion
   (dépôts ET retraits). Demandez-leur s'ils acceptent plusieurs IP et des plages CIDR.
3. Ces IP sont partagées avec d'autres clients Render. Si MoneyFusion les refuse, utilisez
   le serveur dédié : `deploy/vps/README.md`.

## 5. Webhook MoneyFusion (facultatif : le contrôle automatique suffit)
`https://<votre-service>.onrender.com/webhooks/moneyfusion/<MONEYFUSION_WEBHOOK_SECRET>`
(le secret se lit dans Render → Environment).

## 6. Vérifications après déploiement
- [ ] `https://<service>/health` répond.
- [ ] Logs : `[nexmarket] conteneur lance`, aucune ligne « ABSENTE » de `check_env`.
- [ ] Ouvrir `https://pay.moneyfusion.net/api/v1/withdraw/methods` : pays et réseaux visibles.
- [ ] Petit dépôt réel (montant minimum) : crédité, puis petit retrait vers votre numéro.
- [ ] Petit achat test d'une annonce : fonds bloqués, puis libération admin, puis versement
      automatique au vendeur.
- [ ] Si MoneyFusion répond « IP non autorisée » : l'IP n'est pas (encore) enregistrée.
