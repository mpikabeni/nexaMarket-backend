-- v19 : versement des commissions vers le compte JessiKaPay NexMarket.
-- La table est aussi créée automatiquement au démarrage (create_all) ;
-- ce script sert seulement si vous préférez la créer à la main.
CREATE TABLE IF NOT EXISTS commission_payouts (
  id SERIAL PRIMARY KEY,
  transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
  reference VARCHAR(150) NOT NULL UNIQUE,
  amount NUMERIC(18,2) NOT NULL,
  currency VARCHAR(10) NOT NULL DEFAULT 'XAF',
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  jessikapay_transaction_id VARCHAR(255),
  failure_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  sent_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_commission_payouts_status ON commission_payouts(status);
