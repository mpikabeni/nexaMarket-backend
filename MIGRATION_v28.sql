-- v28 : retraits MoneyFusion (pays + réseau + numéro Mobile Money).
-- Ces colonnes sont AUSSI ajoutées automatiquement au démarrage (db.py,
-- SCHEMA_PATCHES) ; ce script sert seulement si vous préférez les créer à la main.
-- Les colonnes jessikapay_* gardent leur nom : elles contiennent maintenant le
-- jeton MoneyFusion (deposits.jessikapay_request_id = token du dépôt,
-- withdrawals.jessikapay_transaction_id = tokenPay du retrait).
ALTER TABLE withdrawals ALTER COLUMN jessikapay_jp_number DROP NOT NULL;
ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS payout_country  VARCHAR(10);
ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS payout_method   VARCHAR(60);
ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS payout_phone    VARCHAR(40);
ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS payout_currency VARCHAR(10);
ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS payout_amount   NUMERIC(18,2);
