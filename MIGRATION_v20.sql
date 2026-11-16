-- v20 : paiement en GRAM (TON). Ces colonnes sont aussi ajoutées
-- automatiquement au démarrage ; ce script sert si vous préférez le faire à la main.
ALTER TABLE listings ADD COLUMN IF NOT EXISTS seller_gram_address VARCHAR(80);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS buyer_gram_address VARCHAR(80);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS seller_gram_address VARCHAR(80);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS gram_tx_hash VARCHAR(120);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS gram_release_tx_hash VARCHAR(120);
CREATE INDEX IF NOT EXISTS ix_transactions_gram_tx_hash ON transactions (gram_tx_hash);
