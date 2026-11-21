# v18 — confirmations automatiques, retrait min 1000, discussion de transaction

## Dépôts / retraits : plus de validation manuelle
- Dépôt : la demande est confirmée par l'utilisateur -> le bot l'informe ;
  dès que JessiKaPay confirme (vérification toutes les 15 s), le wallet est
  crédité automatiquement et le bot écrit à l'utilisateur
  (+ copie d'information aux admins, sans action à faire).
- Retrait : minimum 1 000 XAF (variable Render `MIN_WITHDRAWAL_XAF`,
  contrôlé côté serveur ET dans la Mini App). Dès que JessiKaPay accepte,
  le retrait est terminé et le bot prévient l'utilisateur (+ copie admins).
- Échec / expiration : le bot prévient l'utilisateur, les fonds sont rendus.
- Seul cas qui demande encore un humain : JessiKaPay ne répond pas
  (timeout). Les fonds restent bloqués, l'admin reçoit une alerte dans le bot
  et tranche dans la console > Retraits à vérifier.
- Fichiers : services/money_notifications.py (nouveau), deposit_sync.py,
  routes/deposits.py, routes/withdrawals.py, routes/admin.py, config.py.

## Transactions : discussion acheteur / vendeur / admin
- À l'achat (fonds bloqués) : un message système ouvre la discussion et le bot
  prévient acheteur, vendeur et admin(s), avec boutons « Répondre » et
  « Continuer dans la Mini App » / « Ouvrir la console ».
- Un seul fil partagé. Chaque message (Mini App, console admin ou bot) est
  enregistré puis relayé par le bot aux autres participants.
- Depuis le bot : bouton « Répondre » (ou réponse Telegram directe au
  message), `/stop` pour quitter.
- Admin en charge : le premier admin qui écrit est assigné automatiquement
  s'il n'y en a pas ; ensuite seul cet admin reçoit les messages dans le bot
  (tant qu'aucun admin n'est assigné, tous les admins les reçoivent).
- Console admin : discussion intégrée au détail d'une transaction.
- Mini App : rôle + nom de chaque auteur, messages système, actualisation
  automatique toutes les 5 s.
- Fichiers : services/chat_service.py (nouveau), routes/messages.py,
  services/transaction_service.py, bot.py, services/notification_service.py.

Aucune migration SQL nécessaire.

---

# v19 — argent réel : plus aucun crédit sans JessiKaPay + commissions versées

- **Crédit manuel supprimé** : `POST /admin/deposits/{id}/credit` ne crédite
  plus rien lui-même, il force seulement une revérification auprès de
  JessiKaPay. Le wallet n'est crédité que si JessiKaPay confirme le paiement
  (montant jamais inférieur au montant demandé). Bouton « Créditer » retiré
  de la console.
- **Commissions** : à la fin de chaque transaction, un ordre de versement
  (table `commission_payouts`, un seul par transaction) est créé dans le même
  commit que la vente. Une tâche de fond (20 s) verse la commission sur
  `NEXA_JP_NUMBER` via un payout JessiKaPay. Le bot prévient les admins à
  chaque versement ; timeout/refus -> alerte + `GET /admin/commissions` et
  `POST /admin/commissions/{id}/resolve` (sent | retry).
- Sécurité : statut « sending » enregistré avant l'appel, aucun renvoi
  automatique après timeout, 5 essais max après refus explicite.
- Nouveaux fichiers : services/commission_service.py, MIGRATION_v19.sql.

- **Ajout d'admins** : `/addadmin TELEGRAM_ID` et `/removeadmin TELEGRAM_ID`
  dans le bot, `POST /admin/admins` et `DELETE /admin/admins/{telegram_id}`
  (bouton « + Ajouter un admin » dans la console). Réservé à l'admin
  principal (ADMIN_TELEGRAM_ID) ; il ne peut pas être retiré.

- **Statuts « payé » resserrés** : seuls paid / completed / success /
  successful / succeeded créditent le wallet. Autre mot de JessiKaPay :
  variable Render `JESSIKAPAY_PAID_STATUSES` (séparés par des virgules).

- **Commission verrouillée à 5 %** : le taux est forcé à 0,05 dans la config
  (même si NEXMARKET_FEE_RATE est modifiée sur Render) et dans chaque nouvelle
  transaction (le taux stocké sur d'anciennes annonces est ignoré).

- **Devise d'affichage (EUR / USD) + langue** : nouvelle route publique
  `GET /api/rates` (EUR = parité fixe 655,957 ; USD via open.er-api.com, cache
  6 h, variable optionnelle `USD_XAF_RATE` pour imposer un taux). Affichage
  indicatif uniquement : l'argent réel reste en XAF.

- **Montants entiers vers JessiKaPay** (doc : `amount` = int en FCFA) : retraits
  et versements de commission envoient des entiers (commission arrondie à
  l'entier inférieur).

- **Dépôts : le wallet est crédité du montant NET** (option B). JessiKaPay
  prélève 6 % sur ce que NexMarket reçoit (doc) : 20 000 F déposés -> 18 800 F
  sur le wallet, commission de 1 200 F enregistrée (commission_amount /
  net_amount_credited). Net arrondi vers le bas : jamais plus que ce qui est
  reçu. Nouvelle route `GET /api/deposits/fees` ; l'écran de dépôt affiche
  frais, montant reçu et total à payer (≈ +3 % Mobile Money) avant de payer.
  Variables optionnelles : JESSIKAPAY_DEPOSIT_COMMISSION_RATE (0.06),
  JESSIKAPAY_USER_FEE_RATE (0.03).

- **Dépôt jamais confirmé : lien JessiKaPay ouvert dans Telegram.** Le lien
  (https://t.me/JessiKaPayBot/app?startapp=extdeposit_…) est un lien Telegram :
  l'app l'ouvrait avec openLink (comme un site web) -> JessiKaPay ne reconnaissait
  pas le compte Telegram et le paiement n'était jamais fait. Il s'ouvre maintenant
  avec openTelegramLink. `telegram_id` est envoyé en entier (comme dans la doc).
  Le serveur garde l'étape réelle chez JessiKaPay (pending / reviewing /
  awaiting_payment) ; si rien n'est reçu au bout de 90 s, l'app conseille
  d'ouvrir le lien depuis Telegram avec le même compte.

- **Dépôt payé chez JessiKaPay mais pas crédité** : le contrôle de montant est
  assoupli (on accepte tout montant déclaré >= au net à créditer, quelle que
  soit la façon dont l'API remplit « amount »). Si un dépôt payé ne peut pas
  être crédité, la raison est enregistrée (failure_reason) et les admins sont
  prévenus dans le bot, une seule fois. « Revérifier » (console admin) relance
  le crédit.

# v20 — Paiement en GRAM (TON) : deuxième moyen de paiement

Le vendeur choisit, par annonce, JessiKaPay (FCFA) ou GRAM. En GRAM :
1. Vendeur : saisit son adresse GRAM à la création (somme de contrôle vérifiée).
2. Acheteur : saisit son adresse (remboursement), puis envoie le prix à l'adresse
   de NexMarket avec un commentaire unique (NMX-G-XXXXXXXXXX).
3. Le serveur LIT la blockchain (toncenter, sans clé privée) toutes les 20 s :
   bon commentaire + bon montant + transaction réussie -> escrow normal
   (discussion, transfert du canal, période de protection).
4. À la fin, l'admin reçoit une alerte dans le bot et dans la console (onglet
   GRAM) : il envoie lui-même prix - 5 % au vendeur (la commission reste dans
   son portefeuille) puis saisit le hash ; le serveur le vérifie sur la
   blockchain avant de clôturer. Même principe pour un remboursement.

Configuration (Render) : GRAM_RECEIVE_ADDRESS = adresse du portefeuille NexMarket
(copiée depuis l'app « Argent »). Optionnel : TON_API_KEY, TON_API_BASE.
Vide ou invalide = paiement GRAM désactivé (erreur claire dans les logs).
Nouvelles colonnes ajoutées automatiquement au démarrage (MIGRATION_v20.sql).

- **Retraits : jamais « terminé » sans confirmation de JessiKaPay.** Une réponse
  sans `success: true` / `transaction_id` laisse le retrait « à vérifier »
  (fonds bloqués, admin alerté) ; `success: false` = refus (fonds rendus).
- **Webhook JessiKaPay** `POST /api/webhooks/jessikapay` (signature HMAC vérifiée) :
  `credit.completed` termine un retrait « à vérifier » ; `deposit.completed`
  déclenche la vérification du dépôt (le crédit reste conditionné à la
  vérification auprès de JessiKaPay). À activer en donnant cette URL HTTPS
  (https://VOTRE-SERVICE.onrender.com/api/webhooks/jessikapay) comme `webhook_url`
  de l'application JessiKaPay.

# v21 — Assistant IA des transactions + aperçu des canaux privés

**Assistant IA (Groq / Gemini, gratuits)** : dès que les fonds sont bloqués, « l'Assistant IA
NexMarket » prend la parole dans la discussion acheteur / vendeur / admin (et
dans leurs messages Telegram du bot), guide chacun pour le transfert du canal et
répond à leurs questions. Il est SUPERVISÉ :
- il ne touche jamais à l'argent ni au statut de la transaction ;
- il n'autorise rien : l'accord de transfert vient de l'administrateur (bouton
  « ✅ Autoriser le transfert » dans le bot, ou console) ;
- quand le vendeur est prêt, un doute ou un litige apparaît, l'admin reçoit une
  alerte avec le bouton d'accord ;
- garde-fous : ne demande jamais mot de passe / code, ne dit jamais « paiement
  reçu », n'ordonne pas le transfert avant l'accord ; limite de 60 messages par
  transaction.
Configuration (Render) : deux fournisseurs GRATUITS en cascade. Une seule clé
suffit ; avec les deux, si l'un est limité ou en panne, l'assistant passe à l'autre :
- GROQ_API_KEY   (https://console.groq.com/keys)
- GEMINI_API_KEY (https://aistudio.google.com/apikey)
ASSISTANT_PROVIDERS = ordre d'essai (défaut groq,gemini). Modèles réglables :
GROQ_MODEL, GEMINI_MODEL.

**Canaux privés** : le vendeur ajoute 1 à 6 photos d'aperçu (obligatoire), que
les acheteurs voient en cliquant sur l'annonce (galerie + visionneuse). Les
photos de preuve restent réservées à l'admin. Nouvelle colonne
listing_proofs.kind (ajoutée automatiquement au démarrage).

**Vente** : le moyen de paiement se choisit d'abord (JessiKaPay OU GRAM) ; une
fois choisi, plus aucune trace de l'autre dans le formulaire (bouton « Changer »).

# v26 — Capture d'écran de preuve du transfert (bot)

Quand le vendeur annonce avoir transféré la propriété du canal (statut « transfert
commencé »), l'assistant lui demande une capture d'écran : la liste des
administrateurs du canal où l'acheteur apparaît comme « Propriétaire » (sans mot de
passe ni code visible). Le déclencheur est côté serveur (détection de « c'est fait »,
« transféré », « done »…) : la demande ne dépend pas du hasard du modèle.
- Le bot accepte maintenant les photos (et images envoyées comme fichier) dans une
  discussion ouverte ; la capture est relayée à l'administrateur et à l'acheteur.
- L'assistant NE VOIT PAS l'image : il remercie, alerte l'administrateur et ne confirme
  jamais le transfert. L'administrateur vérifie la capture puis marque le transfert
  terminé.

# v27 — Capture de l'acheteur + diffusion admin avec photo

**Acheteur** : comme le vendeur, il envoie une capture d'écran du canal où il apparaît
comme « Propriétaire ». L'assistant la demande (à l'annonce du vendeur, en période de
protection, ou si l'acheteur dit « j'ai reçu le canal »), remercie, alerte l'administrateur
et NE confirme jamais la réception à sa place. L'image est relayée à l'admin et au vendeur.

**Admins** : /broadcast accepte une PHOTO avec légende (en plus du texte). Le message est
copié tel quel (copy_message) : mise en forme conservée (gras, italique, liens, spoilers).
Limite Telegram : les emojis animés Premium ne sont affichés que si le bot y est autorisé
(sinon l'emoji normal s'affiche). En discussion de transaction, l'admin peut aussi envoyer
des photos (relayées à l'acheteur et au vendeur).
Correctif : un message de diffusion n'est plus aussi posté dans une discussion ouverte.


**Nouvelle annonce** : quand l'admin approuve une annonce pour la première fois, TOUS les
membres actifs du bot (sauf le vendeur) reçoivent « Nouveau canal à vendre » : nom, catégorie,
abonnés, prix et un bouton qui ouvre NexMarket. Envoi en tâche de fond (≈ 20 messages/s,
l'admin n'attend pas). Une annonce modifiée puis ré-approuvée ne re-notifie pas.
Désactivable : NOTIFY_NEW_LISTINGS=false.

## v28
- Photos de preuve facultatives (canaux publics sans photo, canaux privés avec photos d'aperçu).
- Minimum de 1 000 abonnés pour soumettre un canal et créer une annonce (variable `MIN_CHANNEL_SUBSCRIBERS`).
- Prix GRAM au cours du marché : le vendeur fixe le prix en FCFA, le prix en GRAM est recalculé toutes les 10 min
  (tonapi.io, secours CoinGecko) puis figé sur la transaction à l'achat. Nouvelle colonne `listings.price_xaf`
  (ajoutée automatiquement, voir MIGRATION_v28.sql). Variables optionnelles : `GRAM_RATE_REFRESH_SECONDS` (600),
  `GRAM_XAF_RATE` (cours manuel en FCFA pour 1 GRAM). `GET /rates` expose `gram.xaf_per_gram`.
