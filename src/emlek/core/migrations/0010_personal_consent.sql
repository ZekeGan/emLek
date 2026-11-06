-- Broader consent must not inherit a previous medium-only acknowledgement.
UPDATE notice_settings SET enabled = 1, acknowledged_at = NULL WHERE level = 'medium';
DELETE FROM confirm_tokens WHERE kind = 'notice';
UPDATE auto_categories SET mode = 'auto' WHERE mode = 'ask';

-- New vaults are ready for automatic recording, but still require the first consent token.
-- An existing vault's explicit on/off setting is preserved.
UPDATE meta SET value = '1' WHERE key = 'auto_enabled'
    AND NOT EXISTS (SELECT 1 FROM meta WHERE key = 'created_at');
