-- =====================================================================
-- NEXMARKET - Migration de base de données (PostgreSQL)
--
-- À exécuter UNE FOIS si votre base existe déjà.
-- (SQLAlchemy create_all() crée les tables manquantes mais ne modifie
--  JAMAIS une table existante : sans ce script, le code corrigé
--  planterait avec "column ... does not exist".)
-- Si votre base est vide / jetable : supprimez-la et laissez l'appli
-- la recréer, ce script n'est alors pas nécessaire.
-- FAITES UNE SAUVEGARDE AVANT.
-- =====================================================================

BEGIN;

-- 1) IDs Telegram : 32 bits -> 64 bits
--    (un ID de canal comme -1001234567890 dépasse la limite INTEGER)
ALTER TABLE channels     ALTER COLUMN telegram_channel_id TYPE BIGINT;
ALTER TABLE channels     ALTER COLUMN owner_telegram_id   TYPE BIGINT;
ALTER TABLE messages     ALTER COLUMN sender_telegram_id  TYPE BIGINT;
ALTER TABLE transactions ALTER COLUMN telegram_chat_id    TYPE BIGINT;

-- 2) transactions : dates avec fuseau horaire
ALTER TABLE transactions
  ALTER COLUMN created_at            TYPE TIMESTAMPTZ USING created_at            AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at            TYPE TIMESTAMPTZ USING updated_at            AT TIME ZONE 'UTC',
  ALTER COLUMN payment_confirmed_at  TYPE TIMESTAMPTZ USING payment_confirmed_at  AT TIME ZONE 'UTC',
  ALTER COLUMN assigned_at           TYPE TIMESTAMPTZ USING assigned_at           AT TIME ZONE 'UTC',
  ALTER COLUMN completed_at          TYPE TIMESTAMPTZ USING completed_at          AT TIME ZONE 'UTC',
  ALTER COLUMN cancelled_at          TYPE TIMESTAMPTZ USING cancelled_at          AT TIME ZONE 'UTC',
  ALTER COLUMN transfer_started_at   TYPE TIMESTAMPTZ USING transfer_started_at   AT TIME ZONE 'UTC',
  ALTER COLUMN transfer_completed_at TYPE TIMESTAMPTZ USING transfer_completed_at AT TIME ZONE 'UTC';

-- 3) transactions : colonnes qui manquaient (utilisées par le code)
ALTER TABLE transactions
  ADD COLUMN IF NOT EXISTS platform_fee_rate                NUMERIC(8,6) NOT NULL DEFAULT 0.05,
  ADD COLUMN IF NOT EXISTS escrow_held                      BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS escrow_held_at                   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS protection_ends_at               TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS buyer_confirmed_at               TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS disputed_at                      TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS dispute_resolved_at              TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS seller_paid_at                   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS nexmarket_fee_recorded_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS refunded_at                      TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS refund_reference                 VARCHAR(255);

-- Anciens champs du flux de paiement externe, s'ils existent :
ALTER TABLE transactions
  DROP COLUMN IF EXISTS jessikapay_request_id,
  DROP COLUMN IF EXISTS seller_payout_reference,
  DROP COLUMN IF EXISTS jessikapay_payout_transaction_id;

-- Les dépôts n'ont plus de pays (déduit du numéro par JessiKaPay).
ALTER TABLE deposits DROP COLUMN IF EXISTS country;


-- 4) annonces : statuts alignés sur le nouveau cycle de vie
--    (uniquement utile si vous avez déjà des annonces)
UPDATE listings SET status = 'pending_review' WHERE status = 'pending';
-- 'available' = annonce validée dans l'ancien code :
UPDATE listings SET status = 'published', is_public = TRUE WHERE status = 'available';

-- 5) comptes créés par le bot sans wallet
INSERT INTO wallets (user_id, available_balance, blocked_balance, total_revenue, currency, created_at, updated_at)
SELECT u.id, 0, 0, 0, 'XAF', NOW(), NOW()
FROM users u
LEFT JOIN wallets w ON w.user_id = u.id
WHERE w.id IS NULL;

COMMIT;
