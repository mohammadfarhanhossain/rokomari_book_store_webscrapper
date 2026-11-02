INSERT INTO sources (code, name, base_url, is_active)
VALUES ('rokomari', 'Rokomari', 'https://www.rokomari.com', 1)
ON DUPLICATE KEY UPDATE name = VALUES(name), base_url = VALUES(base_url);
