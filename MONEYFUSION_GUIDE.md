# NexMarket × MoneyFusion — mise en service (v28)

MoneyFusion remplace JessiKaPay : **dépôts** (page de paiement hébergée) et
**retraits Mobile Money** vers tous les pays/réseaux que MoneyFusion propose.
Doc officielle : https://docs.moneyfusion.net

## 1. Ce qu'il faut côté MoneyFusion
1. Un compte MoneyFusion **entreprise** et une **application** (nom + URL du site).
   L'URL du site doit être le domaine de `FRONTEND_URL` : MoneyFusion n'accepte
   que des retours (`return_url`) vers ce domaine.
2. Le **lien d'API** de l'application → `MONEYFUSION_API_URL` (il contient votre clé).
3. La **clé privée** (retraits) → `MONEYFUSION_PRIVATE_KEY`.
4. **IP du serveur enregistrée** chez MoneyFusion (retraits ET dépôts : toute IP non
   enregistrée est refusée). Il faut une **IP sortante fixe**.
   - Vercel/serverless : pas d'IP fixe par défaut, et ce backend (bot Telegram,
     tâches de fond) n'est pas adapté au serverless. Gardez le backend sur
     Render (vérifiez ses IP sortantes) ou un petit VPS ; Vercel convient au frontend.
5. Un **solde MoneyFusion** suffisant pour les retraits (à confirmer auprès d'eux :
   les retraits sont prélevés sur votre solde marchand).

## 2. Variables Render
| Variable | Rôle |
|---|---|
| `MONEYFUSION_API_URL` | lien d'API des dépôts |
| `MONEYFUSION_PRIVATE_KEY` | clé privée des retraits |
| `MONEYFUSION_WEBHOOK_SECRET` | texte aléatoire long ; active `/webhooks/moneyfusion/<secret>` |
| `PUBLIC_URL` | URL publique du backend (déjà utilisée) |
| `MONEYFUSION_FX_TO_XAF` | *(optionnel)* devises non CFA, ex. `{"GNF":0.07,"CDF":0.21}` |
| `MONEYFUSION_DEPOSIT_FEE_RATE` | estimation affichée des frais de dépôt (défaut 0.05) |
| `NEXA_PAYOUT_COUNTRY/METHOD/PHONE` | compte Mobile Money qui reçoit les commissions (ex. `cg`, `mtn-cg`, numéro) |

Webhook à déclarer dans MoneyFusion (facultatif, le contrôle automatique suffit) :
`https://<votre-backend>/webhooks/moneyfusion/<MONEYFUSION_WEBHOOK_SECRET>`

## 3. Pays et réseaux
- La liste vient de `GET https://pay.moneyfusion.net/api/v1/withdraw/methods`
  (mise en cache 1 h). Aucun pays/réseau n'est écrit en dur ; une liste de secours
  (doc MoneyFusion) ne sert que si l'API est injoignable.
- **XOF et XAF** : parité 1:1, utilisables directement.
- **Autres devises** (CDF, GNF, GHS…) : **masquées** tant qu'aucun taux n'est donné
  dans `MONEYFUSION_FX_TO_XAF` (le serveur ne convertit jamais avec un taux inventé).
  Si vous en ajoutez, mettez les taux à jour vous-même.
- **Dépôts** : seulement les pays à devise CFA (le wallet est en XAF).
- Pour voir exactement ce que MoneyFusion propose : ouvrez l'URL ci-dessus.

## 4. Fonctionnement et sécurité
- **Dépôt** : l'utilisateur est redirigé vers la page MoneyFusion. NexMarket relit le
  statut (`/paiementNotif/{token}`) toutes les 30 s et sur webhook. Le wallet est
  crédité du **montant net confirmé par MoneyFusion** (jamais plus que demandé).
  La référence renvoyée doit être la nôtre, sinon : alerte admin, aucun crédit.
- **Retrait** : fonds bloqués → demande envoyée → statut `processing` avec jeton
  (`tokenPay`) → la tâche de fond relit `/payout/check-status/{token}` :
  `success` = terminé ; `failed` = fonds rendus ; `pending` = on attend.
- **Statut incertain** (timeout, erreur 5xx, réponse sans jeton) : les fonds restent
  bloqués, **aucun remboursement automatique** (risque de double paiement) ; l'admin
  vérifie dans le tableau de bord MoneyFusion puis tranche (« Versé » / « Non versé »).
- **Webhooks non signés** : jamais crus sur parole. Ils déclenchent seulement une
  relecture du statut auprès de l'API.

## 5. À vérifier avec MoneyFusion avant la mise en production
- Le **Congo-Brazzaville** (et chaque pays visé) est-il disponible en **dépôt** ET en
  retrait, pour **MTN et Airtel** ? (La liste de retrait trouvée dans leur doc ne
  listait que MTN pour le Congo ; consultez `/withdraw/methods`.)
- Frais exacts des dépôts et des retraits, montants min/max, plafonds journaliers.
- Qui supporte les frais de retrait (déduits du montant ou de votre solde).
- Possibilité de signer les webhooks et d'avoir une clé d'idempotence sur les retraits.

## 6. Données existantes
Aucune perte : les colonnes `jessikapay_*` gardent leur nom mais contiennent
maintenant les jetons MoneyFusion. Les anciens retraits (numéro JP) restent lisibles.
Les nouvelles colonnes sont créées automatiquement au démarrage (`MIGRATION_v28.sql`
si vous préférez les créer à la main).

## 7. Achat direct et versement automatique au vendeur (v30)
- **Acheteur** : « Acheter » → paiement MoneyFusion direct (aucun dépôt ni retrait).
  Le pays et le numéro du compte sont préremplis. Le réseau (MTN, Airtel…) se choisit
  sur la page MoneyFusion : leur API de dépôt n'a pas de paramètre de réseau.
  Une fois le paiement confirmé, l'achat est créé automatiquement et l'argent est
  bloqué dans le wallet (escrow habituel). Si l'achat devient impossible (annonce
  vendue entre-temps), l'argent reste disponible dans le solde de l'acheteur.
- Le prix est majoré de l'estimation des frais MoneyFusion (`MONEYFUSION_DEPOSIT_FEE_RATE`)
  pour que le net reçu couvre le prix. Si les vrais frais sont plus élevés, le reliquat
  manquant bloque l'achat et l'argent reste dans le solde : ajustez ce taux.
- **Vendeur** : en mettant son canal en vente, il indique son numéro et son réseau
  (annonce en FCFA). Quand l'admin libère les fonds, le montant (prix - commission) est
  versé automatiquement par MoneyFusion (tâche de fond). Sans compte enregistré ou en cas
  d'échec, l'argent reste dans son wallet (retrait manuel possible).
- Versement jamais en double : `transactions.seller_payout_started_at` est posé AVANT l'envoi.

## 8. Frais MoneyFusion (v31b)
- Les frais ne sont plus affichés dans la mini-app : seule la page MoneyFusion les montre.
- Si le net reçu est inférieur au prix du canal, l'achat reste BLOQUÉ : l'argent reste
  disponible dans le solde de l'acheteur, l'acheteur est prévenu (message exact) et les
  admins reçoivent une alerte demandant d'augmenter `MONEYFUSION_DEPOSIT_FEE_RATE`.

## 9. v33
- Canal public : photos de preuve facultatives (l'admin reçoit un message texte).
  Canal privé : preuves + aperçu toujours obligatoires.
- Messages envoyés aux utilisateurs : plus de mention de MoneyFusion (les alertes admin la gardent).

## 10. v34
- Inscription : RU et IN refusés (403) dans /users/me/onboarding.

## 11. v36 — JessiKaPay remplace MoneyFusion (doc : https://jkpay.vercel.app/docs)
- Achat direct : POST /external/v1/deposit-request -> lien Telegram, l'acheteur paie en Mobile Money.
  Il paie +3 %, NexMarket reçoit -6 % : le montant demandé est majoré pour que le NET couvre le prix.
- Versement vendeur et commissions : POST /external/v1/payout vers un numéro JP (gratuit, immédiat).
  Le vendeur saisit son numéro JP (vérifié par lookup). Il retire ensuite depuis JessiKaPay vers son Mobile Money.
- Variables : JESSIKAPAY_API_KEY, JESSIKAPAY_API_SECRET, JESSIKAPAY_BASE_URL, NEXA_JP_NUMBER.
- Webhook à déclarer dans JessiKaPay : https://<ton-api>/api/webhooks/jessikapay (événement deposit.completed).
- Dépôt / retrait manuels : désactivés (HTTP 410).
- Admin : POST /api/admin/wallets/{user_id}/adjust {action: credit|debit, amount, note}.

## 12. v37 — Retirer / Bannir un canal
- DELETE /api/admin/channels/{id}?ban=false : retrait réversible (statut « withdrawn »), le vendeur peut resoumettre.
- DELETE /api/admin/channels/{id}?ban=true : bannissement définitif (statut « removed »).

## 13. v38 — Bot : /retrait et message d'accueil expliquent que l'argent arrive sur le compte JessiKaPay (numéro JP).

## 14. v39 — NEXA ID dans le bot seulement après création du compte
- /start : le NEXA ID n'apparaît que si le compte est créé dans la mini-app (onboarded_at) ou créé avant LEGACY_ACCOUNTS_BEFORE.
- À la fin de la création du compte, le bot envoie le NEXA ID en message.
