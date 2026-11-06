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
