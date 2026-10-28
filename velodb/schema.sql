-- VeloDB / Apache Doris schema for the Queryable Chatbot.
--
-- Replaces the six MongoDB business collections with SQL tables. VeloDB is
-- built on Apache Doris: MySQL wire protocol on port 9030, HTTP Stream Load
-- on 8030.
--
-- Design notes (why this is not a 1:1 copy of the Mongo collections):
--   * UNIQUE KEY on the natural id gives upsert-on-reload, so re-running the
--     loader converges instead of duplicating rows - the same property the
--     Mongo importer got from delete_many({}) + insert_many(), but without
--     emptying the table first.
--   * Doris enforces no FOREIGN KEY and no CHECK constraints. Referential
--     and value validation therefore lives in the loader (velodb/load.py),
--     which refuses a bad batch rather than writing it.
--   * replication_num = 1 suits the single-node dev cluster in
--     docker-compose.yml. Raise it to 3 on a real VeloDB deployment.
--   * DECIMAL, not DOUBLE, for money: spend figures are compared and summed.

CREATE DATABASE IF NOT EXISTS queryable_chatbot;

USE queryable_chatbot;

-- ---------------------------------------------------------------- span_companies
-- The main dataset: 500 HR-tech companies.
CREATE TABLE IF NOT EXISTS span_companies (
    company_id               VARCHAR(16)   NOT NULL COMMENT 'SPAN-nnnn',
    company_name             VARCHAR(128)  NOT NULL,
    industry                 VARCHAR(64)   NOT NULL,
    country                  VARCHAR(64)   NOT NULL,
    employee_count           INT           NOT NULL,
    hr_technology            VARCHAR(64)   NOT NULL,
    technology_category      VARCHAR(32)   NOT NULL,
    deployment_type          VARCHAR(16)   NOT NULL,
    annual_hr_tech_spend_usd DECIMAL(14,2) NOT NULL
)
UNIQUE KEY (company_id)
DISTRIBUTED BY HASH (company_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- ---------------------------------------------------------------- customers
CREATE TABLE IF NOT EXISTS customers (
    customer_id INT         NOT NULL,
    country     VARCHAR(64) NULL,
    signup_date DATE        NULL
)
UNIQUE KEY (customer_id)
DISTRIBUTED BY HASH (customer_id) BUCKETS 2
PROPERTIES ("replication_num" = "1");

-- ---------------------------------------------------------------- products
CREATE TABLE IF NOT EXISTS products (
    product_id   INT          NOT NULL,
    product_name VARCHAR(128) NULL,
    category     VARCHAR(64)  NULL
)
UNIQUE KEY (product_id)
DISTRIBUTED BY HASH (product_id) BUCKETS 1
PROPERTIES ("replication_num" = "1");

-- ---------------------------------------------------------------- orders
CREATE TABLE IF NOT EXISTS orders (
    order_id    INT         NOT NULL,
    customer_id INT         NULL,
    order_date  DATE        NULL,
    status      VARCHAR(32) NULL
)
UNIQUE KEY (order_id)
DISTRIBUTED BY HASH (order_id) BUCKETS 2
PROPERTIES ("replication_num" = "1");

-- ---------------------------------------------------------------- order_items
-- No single natural key in the source CSV (an order may repeat a product),
-- so this uses the DUPLICATE model: every row is kept exactly as loaded.
-- The loader truncates before loading to keep reloads idempotent.
CREATE TABLE IF NOT EXISTS order_items (
    order_id   INT           NOT NULL,
    product_id INT           NOT NULL,
    quantity   INT           NULL,
    price      DECIMAL(12,2) NULL
)
DUPLICATE KEY (order_id, product_id)
DISTRIBUTED BY HASH (order_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- ---------------------------------------------------------------- sales_cleaned
-- Pre-joined fact table from the source project (order + item + revenue).
CREATE TABLE IF NOT EXISTS sales_cleaned (
    order_id    INT           NOT NULL,
    product_id  INT           NOT NULL,
    quantity    INT           NULL,
    price       DECIMAL(12,2) NULL,
    revenue     DECIMAL(14,2) NULL,
    customer_id INT           NULL,
    order_date  DATE          NULL,
    status      VARCHAR(32)   NULL,
    year        INT           NULL,
    month       INT           NULL
)
DUPLICATE KEY (order_id, product_id)
DISTRIBUTED BY HASH (order_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");
