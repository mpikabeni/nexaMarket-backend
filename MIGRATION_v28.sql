-- v28 : prix des annonces GRAM fixé en FCFA, converti au cours du marché.
-- Cette colonne est aussi ajoutée automatiquement au démarrage.
ALTER TABLE listings ADD COLUMN IF NOT EXISTS price_xaf NUMERIC(18,2);
