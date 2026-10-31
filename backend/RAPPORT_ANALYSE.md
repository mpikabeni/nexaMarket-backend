# NexMarket — rapport d'analyse et corrections (backend + frontend)

Méthode : lecture complète du code + analyse statique (compilation, `node --check`, imports,
attributs vs colonnes des modèles, **appels du frontend comparés un par un aux routes du backend :
0 écart**). **Rien n'a pu être exécuté** (pas de réseau ni de FastAPI dans mon environnement).

## 1. Pays retirés (demande)

| Où | Avant | Maintenant |
|---|---|---|
| Frontend : filtres, carte d'annonce, détail, formulaire de vente, formulaire de dépôt | sélecteur / champ « Pays » partout | supprimé |
| Frontend : « Langue » (filtre, carte, formulaire de vente) | affichée, mais **aucune colonne en base** : toujours « — » | supprimé aussi (même raison) |
| Backend : `deposits.py`, schémas, modèle `Deposit`, `deposit_service`, client JessiKaPay | champ `country` obligatoire | supprimé (colonne retirée) |
| Dépôt | pays choisi dans une liste | numéro Mobile Money **avec indicatif** (`+242…`) ; JessiKaPay déduit le pays |

⚠️ Hypothèse à confirmer avec la doc JessiKaPay : que `deposit` n'exige pas de champ `country`.
Si c'est le cas, il suffit de le rajouter dans `create_deposit_request` (services/jessikapay.py), un seul endroit.

## 2. Incohérence majeure corrigée : modèle de paiement

Le frontend fonctionne en **portefeuille** (dépôt → solde → achat → retrait). Le backend, lui, faisait un
paiement externe par « demande de paiement » : acheteur jamais débité, flux impossible. Aligné sur le
modèle wallet (celui de l'ancien `routes/transaction.py`) :

1. `POST /transactions` : crée la transaction **et bloque** le prix dans le wallet de l'acheteur (solde insuffisant → erreur claire, l'annonce est remise en vente).
2. Un admin s'assigne la transaction, démarre puis termine le transfert du canal.
3. Période de protection (60 min) ; l'acheteur peut confirmer la réception (`/confirm-receipt`) ou ouvrir un litige.
4. Fin de protection **sans litige** → clôture **automatique** (tâche toutes les 5 min) : fonds consommés chez l'acheteur, vendeur crédité (prix − commission), commission enregistrée dans le wallet plateforme, annonce « vendue ».
5. Litige → l'admin tranche via `POST /transactions/{id}/resolve` : `refund_buyer` (**remboursement**, qui manquait) ou `release_seller`.
6. Annulation possible avant le début du transfert, avec remboursement automatique.

Tous les mouvements ont une référence unique (rejouable sans double paiement). JessiKaPay ne sert plus qu'aux **dépôts et retraits**.
Supprimés car sans objet : routes `payment`, `payment/check`, `payout`, événements webhook `payment.completed` et payout vendeur, colonnes `jessikapay_request_id` / `seller_payout_reference` / `jessikapay_payout_transaction_id`.

## 3. Autres corrections — backend

**Sécurité / argent** : webhook JessiKaPay sans authentification (secret obligatoire + recoupement dépôt/montant/utilisateur) ·
wallet sans verrou de ligne (double dépense) · retrait rendu sur simple timeout (double paiement) · `nexa_id` qui exposait le telegram_id ·
JWT_SECRET trop court accepté · `admin_note` exposée aux utilisateurs · transfert déclenchable par le vendeur.

**Crashs** : 14 colonnes absentes du modèle `Transaction` · dates sans fuseau (asyncpg) · IDs Telegram en 32 bits (un ID de canal `-100…` ne rentre pas) ·
`listings.py` écrit pour d'anciens modèles (réécrit en async) · statuts d'annonce incohérents (`pending`/`pending_review`/`available`/`published`) ·
deux clients JessiKaPay dupliqués avec deux `JessiKaPayError` · méthodes appelées mais inexistantes · erreurs métier renvoyées en HTTP 500 ·
endpoint `lookup` collé après un `return` · utilisateurs créés par le bot sans wallet · `reviews` jamais enregistré · bot en double dans `render.yaml` ·
`POST /transactions`, `POST /channels`, rejets admin, résolution de signalements : paramètres d'URL à la place de corps JSON.

**Dernière passe (fichiers relus en détail : messages, signalements, avis, favoris, utilisateurs, bot, notifications)**
- `GET /users/me/wallet` : accès à une relation ORM paresseuse (`current_user.wallet`) = `MissingGreenlet` en async → erreur 500. Lecture via `WalletService` (wallet créé s'il manque).
- `reports.py` : un signalement faisait passer **n'importe quelle** transaction en « litige », y compris non payée → transaction et annonce bloquées à vie (plus d'annulation possible). Limité aux transactions payées (fonds bloqués) et non soldées ; un signalement déjà clos ne peut plus être re-clos.
- `messages.py` : les messages supprimés (suppression logique) étaient toujours renvoyés ; corrigé (liste utilisateur et admin).
- **Notifications Telegram** : `NotificationService` n'était appelé nulle part (ni le vendeur ni l'acheteur n'étaient prévenus). Branché, en « best effort » non bloquant (une notification ratée ne casse jamais un achat) : achat / vente, début et fin de transfert, clôture, remboursement, annulation, litige, annonce approuvée / refusée.
- `channels.py` : un nouveau `Bot` Telegram (session HTTP) créé à chaque requête et jamais fermé → instance partagée.
- `favorites.py` : ne renvoyait pas le canal (nom, abonnés) → cartes vides côté frontend ; même format que `/listings`.
- `bot.py` : libellés de statuts de transaction obsolètes (`payment_confirmed`, `assigned`, `transfer_pending`) → statuts réels.
- Vérifié automatiquement : 0 import cassé, 0 cycle d'import, 0 attribut inexistant, 0 argument de constructeur de modèle invalide, 0 écart frontend ↔ routes.

**Flux « canal → annonce » du frontend** : le backend exigeait l'approbation admin du canal *avant* de créer l'annonce, alors que le frontend enchaîne les deux.
Maintenant : le canal (propriétaire + bot vérifiés par Telegram) peut être « submitted », et **approuver l'annonce approuve aussi le canal**.
`POST /channels` accepte le simple `@username` (l'ID numérique est résolu via Telegram) et refuse enfin les canaux non vérifiés / dont l'utilisateur n'est pas propriétaire.

**Admin** : ajout de `/admin/me`, `/admin/channels`, `/admin/messages`, `/admin/listings/{id}`, `/admin/platform-wallet` ; tableau de bord corrigé (statut `transfer_started`, solde plateforme).

**Divers** : expiration des réservations impayées · annonce « vendue » en fin de transaction · validations (montants NaN, numéro JP, plafonds) ·
Dockerfile non-root + healthcheck · `render.yaml` : worker supprimé, variables JessiKaPay/admin ajoutées, **nom du service = `nexamarket-backend`** (l'URL appelée par le frontend).

## 4. Corrections — frontend

- **12 fonctions définies deux fois** dans `app.js` (la 2ᵉ copie écrasait la 1ʳᵉ, ~950 lignes mortes). La copie supprimée était celle qui **faisait disparaître la barre de catégories** de l'écran « Acheter » : elle est restaurée.
- Routes qui n'existaient pas : `GET /wallet`, `POST /messages`, `POST /favorites/{id}`, et côté admin `/admin/verifications`, `/admin/wallet`, `/admin/listings/{id}/decision`, `/admin/transactions/{id}/action`, `/admin/reports/{id}/resolve`.
- `POST /channels` / `POST /listings` : la catégorie choisie n'était pas envoyée avec l'annonce ; champs inutiles retirés.
- **Écran de transaction** : libellés de statuts alignés sur le backend ; boutons selon le statut et le rôle : *J'ai bien reçu le canal*, *Ouvrir un litige*, *Annuler* ; solde rafraîchi après achat / annulation.
- Statuts de « mes annonces » (`pending_review`, `published`…) alignés ; bouton « Modifier » corrigé (testait l'ancien statut `available`).
- Panneau admin : ne lisait aucune liste (le backend renvoie `{users:[…]}`) ; la page chargée par `/admin/` était une **maquette incompatible** avec `admin.js` → `admin/index.html` redirige vers `admin.html` ; boutons d'action sur les transactions (assigner, transfert, rembourser, payer le vendeur) ; le login admin envoie maintenant `X-Telegram-Init-Data` (requis par le backend).
- **Styles manquants (écran « Acheter » et autres)** : 49 classes utilisées par `app.js` n'avaient *aucune* règle dans `style.css` (le fichier lui-même est valide). Ajout d'un bloc « STYLES COMPLÉMENTAIRES » : barre de catégories (qui n'a jamais eu de CSS), détail d'annonce (vérifications, vendeur), recherche de compte JessiKaPay, mes annonces / modification, liste et détail des transactions, messages (bulles), favoris, FAQ / support, bouton `full-width` (n'existait que dans le formulaire de vente). Version de cache (`?v=`) changée dans `index.html` pour forcer le rechargement. Console admin : `.row.between` stylé.
- Délai de requête 15 s → 45 s (démarrage à froid de Render).

## 5. À faire de votre côté

1. **Exécuter `MIGRATION.sql`** si la base existe déjà (sauvegarde avant) : types 64 bits, dates avec fuseau, colonnes ajoutées/retirées, statuts d'annonces, wallets manquants.
2. Variables Render : `JESSIKAPAY_WEBHOOK_SECRET` (+ le même secret chez JessiKaPay, en-tête `X-Webhook-Secret` ou `?token=`), `ADMIN_TELEGRAM_ID`, `ADMIN_CODE`, `JWT_SECRET` (≥ 32 caractères).
3. Vérifier avec la doc JessiKaPay : dépôt sans `country`, champs des webhooks `deposit.completed` et `credit.completed`.
4. La console admin doit être ouverte **depuis la Mini App Telegram** (5 taps sur le logo) : le backend contrôle le compte Telegram.
5. **Tester en préproduction avec de petits montants** avant tout argent réel : dépôt → achat → transfert → clôture → retrait, puis le cas litige/remboursement.

## 6. Limites (honnêteté)

- **Aucun test d'exécution.** Syntaxe Python/JS, imports, signatures d'appels et correspondance frontend ↔ routes vérifiés statiquement uniquement.
- Relus en détail : auth, wallet, transactions, listings, channels, webhooks, deposits, withdrawals, admin, messages, reports, reviews, favorites, users, notifications, frontend (flux principaux). `bot.py` (1 400 lignes de commandes Telegram) : seulement parcouru et vérifié pour les imports, statuts et attributs de modèles.
- Fenêtre de panne très étroite : si le serveur s'arrête exactement entre le blocage des fonds et l'écriture de la transaction, les fonds restent bloqués (visible dans `wallet_operations`, à régulariser à la main).
- `deposit_service.py` / `withdrawal_service.py` ne sont appelés par aucune route (code dormant, rendu cohérent).
- Pas d'Alembic : les évolutions de schéma passent par SQL manuel. Base Render « free » à remplacer avant la production.
