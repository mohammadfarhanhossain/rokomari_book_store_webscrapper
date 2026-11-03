-- Catalog Schema Migration for Rokomari (rokomari)
-- Compatible with MySQL 8.x / MariaDB and PostgreSQL

CREATE TABLE IF NOT EXISTS sources (
  source_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(32) NOT NULL,
  name VARCHAR(100) NOT NULL,
  base_url VARCHAR(500) NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_sources_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS authors (
  author_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  canonical_name VARCHAR(255) NOT NULL,
  normalized_name VARCHAR(255) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_authors_normalized_name (normalized_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS publishers (
  publisher_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  canonical_name VARCHAR(255) NOT NULL,
  normalized_name VARCHAR(255) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_publishers_normalized_name (normalized_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS subjects (
  subject_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  canonical_name VARCHAR(255) NOT NULL,
  normalized_name VARCHAR(255) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_subjects_normalized_name (normalized_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS books (
  book_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  book_name VARCHAR(500) NOT NULL,
  author_id BIGINT UNSIGNED NULL,
  publisher_id BIGINT UNSIGNED NULL,
  subject_id BIGINT UNSIGNED NULL,
  main_price INT NOT NULL DEFAULT 0,
  store_price INT NOT NULL DEFAULT 0,
  book_url VARCHAR(1000) NULL,
  image_url VARCHAR(1000) NULL,
  in_stock BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_books_author (author_id),
  KEY ix_books_publisher (publisher_id),
  KEY ix_books_price (store_price),
  FULLTEXT KEY ft_books_name (book_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
