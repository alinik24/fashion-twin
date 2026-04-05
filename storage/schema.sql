-- ================================================================================================
-- Fashion Twin — Unified Database Schema
-- ================================================================================================
-- AI-powered fashion recommendation system with deal hunting, RLHF, and product enrichment
--
-- Run: python scripts/init_db.py
-- Or:  psql $POSTGRES_DSN -f storage/schema.sql
-- ================================================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ================================================================================================
-- CORE TABLES
-- ================================================================================================

-- Items: Scraped fashion items from marketplaces
CREATE TABLE IF NOT EXISTS items (
    id              SERIAL PRIMARY KEY,
    external_id     VARCHAR(200)    NOT NULL,
    source          VARCHAR(50)     NOT NULL,   -- 'vinted', 'vestiaire', 'depop'
    title           TEXT,
    description     TEXT,
    brand           VARCHAR(200),
    size            VARCHAR(50),
    condition       VARCHAR(50),
    price           FLOAT,
    currency        VARCHAR(10),
    image_url       TEXT,
    listing_url     TEXT            NOT NULL,
    catalog_id      INTEGER,
    color1          VARCHAR(100),
    raw_data        JSONB,
    scraped_at      TIMESTAMPTZ     DEFAULT NOW(),
    embedded_at     TIMESTAMPTZ,
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_items_source      ON items (source);
CREATE INDEX IF NOT EXISTS idx_items_brand       ON items (brand);
CREATE INDEX IF NOT EXISTS idx_items_price       ON items (price);
CREATE INDEX IF NOT EXISTS idx_items_scraped_at  ON items (scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_embedded_at ON items (embedded_at);

-- Interactions: User feedback (explicit + implicit)
CREATE TABLE IF NOT EXISTS interactions (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER         DEFAULT 1,
    item_id          INTEGER         REFERENCES items(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50)     NOT NULL,  -- 'like','dislike','view','skip','purchase'
    strength         FLOAT           DEFAULT 1.0,
    context          JSONB,
    created_at       TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interactions_user    ON interactions (user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_item    ON interactions (item_id);
CREATE INDEX IF NOT EXISTS idx_interactions_type    ON interactions (interaction_type);
CREATE INDEX IF NOT EXISTS idx_interactions_created ON interactions (created_at DESC);

-- Item Embeddings: Pointer to Qdrant vector database
CREATE TABLE IF NOT EXISTS item_embeddings (
    item_id         INTEGER         REFERENCES items(id) ON DELETE CASCADE,
    model_version   VARCHAR(100)    NOT NULL,
    qdrant_id       UUID            NOT NULL DEFAULT uuid_generate_v4(),
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    PRIMARY KEY (item_id, model_version)
);

-- Model Snapshots: Trained model checkpoints
CREATE TABLE IF NOT EXISTS model_snapshots (
    id              SERIAL PRIMARY KEY,
    model_type      VARCHAR(50)     NOT NULL,   -- 'lightfm', 'bandit'
    model_version   VARCHAR(100),
    model_path      TEXT            NOT NULL,
    metrics         JSONB,
    trained_at      TIMESTAMPTZ     DEFAULT NOW()
);

-- Scrape Jobs: Audit log for scraping operations
CREATE TABLE IF NOT EXISTS scrape_jobs (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(50)     NOT NULL,
    query           TEXT,
    pages_requested INTEGER,
    items_found     INTEGER,
    items_new       INTEGER,
    started_at      TIMESTAMPTZ     DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    error           TEXT
);

-- ================================================================================================
-- BEHAVIORAL TRACKING
-- ================================================================================================

-- Behavioral Signals: Implicit feedback from user interactions
-- Reference: Joachims et al. (2005) "Accurately Interpreting Clickthrough Data as Implicit Feedback"
CREATE TABLE IF NOT EXISTS behavior_signals (
    id              SERIAL PRIMARY KEY,
    session_id      UUID,
    user_id         INTEGER         DEFAULT 1,
    item_id         INTEGER         REFERENCES items(id) ON DELETE SET NULL,
    signal_type     VARCHAR(50)     NOT NULL,   -- dwell|click|offer|contact|favorite|scroll_past|share
    value           FLOAT,
    domain          VARCHAR(50)     DEFAULT 'fashion',
    context         JSONB,
    consent_granted BOOLEAN         DEFAULT TRUE,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bsig_user       ON behavior_signals (user_id);
CREATE INDEX IF NOT EXISTS idx_bsig_item       ON behavior_signals (item_id);
CREATE INDEX IF NOT EXISTS idx_bsig_type       ON behavior_signals (signal_type);
CREATE INDEX IF NOT EXISTS idx_bsig_domain     ON behavior_signals (domain);
CREATE INDEX IF NOT EXISTS idx_bsig_session    ON behavior_signals (session_id);
CREATE INDEX IF NOT EXISTS idx_bsig_created    ON behavior_signals (created_at DESC);

-- Tracker Sessions: User browsing sessions
CREATE TABLE IF NOT EXISTS tracker_sessions (
    id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         INTEGER         DEFAULT 1,
    domain          VARCHAR(50)     DEFAULT 'fashion',
    started_at      TIMESTAMPTZ     DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    signal_count    INTEGER         DEFAULT 0,
    metadata        JSONB
);

-- Consent Log: User privacy consent tracking
CREATE TABLE IF NOT EXISTS consent_log (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER         DEFAULT 1,
    domain          VARCHAR(50)     NOT NULL,   -- fashion|food|travel|all
    enabled         BOOLEAN         NOT NULL,
    reason          TEXT,
    changed_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_consent_user   ON consent_log (user_id, domain);

-- Activity Log: General activity tracking (consent-gated)
CREATE TABLE IF NOT EXISTS activity_log (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER         DEFAULT 1,
    session_id      UUID,
    domain          VARCHAR(50)     NOT NULL,   -- fashion|food|travel|tech|fitness|…
    activity_type   VARCHAR(50)     NOT NULL,   -- browse|search|purchase|view|read|…
    payload         JSONB,
    source_url      TEXT,
    consent_granted BOOLEAN         DEFAULT TRUE,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_actlog_user    ON activity_log (user_id);
CREATE INDEX IF NOT EXISTS idx_actlog_domain  ON activity_log (domain);
CREATE INDEX IF NOT EXISTS idx_actlog_created ON activity_log (created_at DESC);

-- ================================================================================================
-- RLHF (Reinforcement Learning from Human Feedback)
-- ================================================================================================

-- Preference Comparisons: Pairwise item preferences
-- Reference: Christiano et al. (2017) "Deep RL from Human Preferences"
-- Reference: Rafailov et al. (2023) "Direct Preference Optimization"
CREATE TABLE IF NOT EXISTS preference_comparisons (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER         DEFAULT 1,
    item_a_id       INTEGER         REFERENCES items(id) ON DELETE CASCADE,
    item_b_id       INTEGER         REFERENCES items(id) ON DELETE CASCADE,
    preferred       VARCHAR(10),                -- 'a'|'b'|'equal'|'skip'
    context_query   TEXT,
    reward_a        FLOAT,
    reward_b        FLOAT,
    llm_reasoning   TEXT,
    source          VARCHAR(50)     DEFAULT 'explicit', -- explicit|implicit|llm_judge
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pref_user      ON preference_comparisons (user_id);
CREATE INDEX IF NOT EXISTS idx_pref_created   ON preference_comparisons (created_at DESC);

-- Reward Scores: Cached reward model predictions
CREATE TABLE IF NOT EXISTS reward_scores (
    id              SERIAL PRIMARY KEY,
    item_id         INTEGER         REFERENCES items(id) ON DELETE CASCADE,
    user_id         INTEGER         DEFAULT 1,
    score           FLOAT           NOT NULL,
    score_breakdown JSONB,
    model_version   VARCHAR(100),
    scored_at       TIMESTAMPTZ     DEFAULT NOW(),
    UNIQUE (item_id, user_id, model_version)
);

CREATE INDEX IF NOT EXISTS idx_reward_item    ON reward_scores (item_id);
CREATE INDEX IF NOT EXISTS idx_reward_score   ON reward_scores (score DESC);

-- Style Profile: User style preferences (inferred + explicit)
CREATE TABLE IF NOT EXISTS style_profile (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER         DEFAULT 1,
    attribute       VARCHAR(100)    NOT NULL,
    value           TEXT            NOT NULL,
    strength        FLOAT           DEFAULT 1.0,
    source          VARCHAR(50)     DEFAULT 'rule', -- rule|inferred|rlhf|explicit
    active          BOOLEAN         DEFAULT TRUE,
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_style_user     ON style_profile (user_id, attribute);
CREATE INDEX IF NOT EXISTS idx_style_active   ON style_profile (user_id) WHERE active = TRUE;

-- User Rules: Explicit filtering and preference rules
CREATE TABLE IF NOT EXISTS user_rules (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER         DEFAULT 1,
    rule_type       VARCHAR(50)     NOT NULL,  -- block|require|prefer|avoid_if
    field           VARCHAR(100)    NOT NULL,  -- brand|material|color|price|condition|…
    operator        VARCHAR(20)     NOT NULL,  -- eq|ne|contains|gt|lt|in|not_in
    value           TEXT            NOT NULL,
    reward_delta    FLOAT           DEFAULT 0.0,
    active          BOOLEAN         DEFAULT TRUE,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rules_user     ON user_rules (user_id) WHERE active = TRUE;

-- Trends: Fashion trend data from external sources
CREATE TABLE IF NOT EXISTS trends (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(100)    NOT NULL,   -- vogue|lyst|pinterest|wgsn
    category        VARCHAR(100),
    trend_text      TEXT            NOT NULL,
    keywords        TEXT[],
    season          VARCHAR(20),
    relevance_score FLOAT,
    scraped_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trends_season  ON trends (season);
CREATE INDEX IF NOT EXISTS idx_trends_src     ON trends (source);
CREATE INDEX IF NOT EXISTS idx_trends_date    ON trends (scraped_at DESC);

-- DPO Training Log: Direct Preference Optimization training history
CREATE TABLE IF NOT EXISTS dpo_training_log (
    id              SERIAL PRIMARY KEY,
    pairs_used      INTEGER,
    loss_before     FLOAT,
    loss_after      FLOAT,
    beta            FLOAT,
    model_path      TEXT,
    trained_at      TIMESTAMPTZ     DEFAULT NOW()
);

-- ================================================================================================
-- DEAL HUNTING & PRICE TRACKING
-- ================================================================================================

-- Price History: Historical price data for items
CREATE TABLE IF NOT EXISTS price_history (
    id              SERIAL PRIMARY KEY,
    item_id         TEXT NOT NULL,
    price           NUMERIC(10, 2) NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'EUR',
    original_price  NUMERIC(10, 2),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source          TEXT
);

CREATE INDEX IF NOT EXISTS idx_price_history_item_time ON price_history (item_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_timestamp ON price_history (timestamp DESC);

-- Price Alerts: Price drop notifications
CREATE TABLE IF NOT EXISTS price_alerts (
    id              SERIAL PRIMARY KEY,
    item_id         TEXT NOT NULL,
    old_price       NUMERIC(10, 2) NOT NULL,
    new_price       NUMERIC(10, 2) NOT NULL,
    drop_percentage NUMERIC(5, 2) NOT NULL,
    drop_amount     NUMERIC(10, 2) NOT NULL,
    alerted         BOOLEAN DEFAULT FALSE,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_alerts_item ON price_alerts(item_id);
CREATE INDEX IF NOT EXISTS idx_price_alerts_not_alerted ON price_alerts(alerted, timestamp) WHERE NOT alerted;

-- Deals Found: Discovered deals with scoring
CREATE TABLE IF NOT EXISTS deals_found (
    id              SERIAL PRIMARY KEY,
    item_id         TEXT NOT NULL UNIQUE,
    title           TEXT,
    price           NUMERIC(10, 2),
    currency        TEXT DEFAULT 'EUR',
    brand           TEXT,
    condition       TEXT,
    url             TEXT,
    image_url       TEXT,
    deal_score      NUMERIC(5, 2),
    deal_quality    TEXT,
    deal_breakdown  JSONB,
    found_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notified_at     TIMESTAMPTZ,
    purchased       BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_deals_found_score ON deals_found(deal_score DESC, found_at DESC);
CREATE INDEX IF NOT EXISTS idx_deals_found_quality ON deals_found(deal_quality, found_at DESC);
CREATE INDEX IF NOT EXISTS idx_deals_found_brand ON deals_found(brand);

-- Hunter Scans: Deal hunting session tracking
CREATE TABLE IF NOT EXISTS hunter_scans (
    id              SERIAL PRIMARY KEY,
    scan_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scan_completed_at TIMESTAMPTZ,
    categories      TEXT[],
    items_scanned   INTEGER DEFAULT 0,
    deals_found     INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    status          TEXT
);

CREATE INDEX IF NOT EXISTS idx_hunter_scans_time ON hunter_scans(scan_started_at DESC);

-- Market Averages: Price benchmarks for categories/brands
CREATE TABLE IF NOT EXISTS market_averages (
    id              SERIAL PRIMARY KEY,
    category        TEXT NOT NULL,
    brand           TEXT,
    condition       TEXT,
    avg_price       NUMERIC(10, 2) NOT NULL,
    min_price       NUMERIC(10, 2) NOT NULL,
    max_price       NUMERIC(10, 2) NOT NULL,
    sample_size     INTEGER NOT NULL,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(category, brand, condition)
);

CREATE INDEX IF NOT EXISTS idx_market_avg_category ON market_averages(category);
CREATE INDEX IF NOT EXISTS idx_market_avg_brand ON market_averages(brand);

-- ================================================================================================
-- PRODUCT ENRICHMENT (Google Lens)
-- ================================================================================================

-- Product Metadata: Enriched product data from Google Lens
CREATE TABLE IF NOT EXISTS product_metadata (
    id              SERIAL PRIMARY KEY,
    item_id         INTEGER UNIQUE REFERENCES items(id) ON DELETE CASCADE,

    -- Google Lens extracted data
    lens_title      TEXT,
    lens_brand      TEXT,
    lens_model      TEXT,
    lens_original_price NUMERIC(10, 2),
    lens_currency   TEXT DEFAULT 'GBP',
    lens_category   TEXT,
    lens_material   TEXT,

    -- Official manufacturer data
    official_name   TEXT,
    official_price  NUMERIC(10, 2),
    official_sku    TEXT,
    materials       JSONB,
    colors          JSONB,
    description     TEXT,
    specifications  JSONB,

    -- Authenticity checking
    authenticity_score INTEGER CHECK (authenticity_score BETWEEN 0 AND 100),
    authenticity_confidence TEXT CHECK (authenticity_confidence IN ('high', 'medium', 'low')),
    authenticity_red_flags JSONB,

    -- Price comparison
    discount_percentage NUMERIC(5, 2),
    deal_quality    TEXT,

    -- Source information
    source_urls     JSONB,
    visual_match_count INTEGER,

    -- Metadata
    enriched_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_metadata_item ON product_metadata(item_id);
CREATE INDEX IF NOT EXISTS idx_product_metadata_brand ON product_metadata(lens_brand);
CREATE INDEX IF NOT EXISTS idx_product_metadata_authenticity ON product_metadata(authenticity_score DESC);
CREATE INDEX IF NOT EXISTS idx_product_metadata_discount ON product_metadata(discount_percentage DESC);

-- ================================================================================================
-- VIEWS
-- ================================================================================================

-- Price Trends: Price movement analysis
CREATE OR REPLACE VIEW price_trends AS
WITH price_changes AS (
    SELECT
        item_id,
        FIRST_VALUE(price) OVER (PARTITION BY item_id ORDER BY timestamp
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as first_price,
        LAST_VALUE(price) OVER (PARTITION BY item_id ORDER BY timestamp
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_price
    FROM price_history
)
SELECT
    ph.item_id,
    MIN(ph.price) as min_price,
    MAX(ph.price) as max_price,
    AVG(ph.price) as avg_price,
    COUNT(*) as data_points,
    MAX(ph.timestamp) - MIN(ph.timestamp) as time_span,
    CASE
        WHEN MAX(pc.first_price) > 0 THEN
            (MAX(pc.last_price) - MAX(pc.first_price)) / MAX(pc.first_price) * 100
        ELSE 0
    END as price_change_pct
FROM price_history ph
LEFT JOIN price_changes pc ON pc.item_id = ph.item_id
GROUP BY ph.item_id;

-- Best Deals: High-scoring recent deals
CREATE OR REPLACE VIEW best_deals AS
SELECT *
FROM deals_found
WHERE deal_score >= 70
  AND found_at > NOW() - INTERVAL '7 days'
  AND NOT purchased
ORDER BY deal_score DESC, found_at DESC;

-- Daily Deal Stats: Aggregated deal metrics by day
CREATE OR REPLACE VIEW daily_deal_stats AS
SELECT
    DATE(found_at) as date,
    COUNT(*) as total_deals,
    COUNT(*) FILTER (WHERE deal_quality = 'excellent') as excellent_deals,
    COUNT(*) FILTER (WHERE deal_quality = 'good') as good_deals,
    AVG(deal_score) as avg_score,
    AVG(price) as avg_price
FROM deals_found
GROUP BY DATE(found_at)
ORDER BY date DESC;

-- Items with Metadata: Enriched items view
CREATE OR REPLACE VIEW items_with_metadata AS
SELECT
    i.external_id AS item_id,
    i.title AS listing_title,
    i.price AS listing_price,
    i.brand AS listing_brand,
    i.image_url,
    pm.lens_title,
    pm.lens_brand,
    pm.lens_model,
    pm.lens_original_price,
    pm.official_name,
    pm.official_price,
    pm.materials,
    pm.authenticity_score,
    pm.authenticity_confidence,
    pm.discount_percentage,
    CASE
        WHEN pm.discount_percentage >= 60 THEN 'excellent'
        WHEN pm.discount_percentage >= 40 THEN 'good'
        WHEN pm.discount_percentage >= 20 THEN 'fair'
        ELSE 'poor'
    END AS deal_quality
FROM items i
LEFT JOIN product_metadata pm ON i.id = pm.item_id;

-- Potential Fakes: Low authenticity items
CREATE OR REPLACE VIEW potential_fakes AS
SELECT
    i.external_id AS item_id,
    i.title,
    i.price,
    pm.lens_brand,
    pm.lens_original_price,
    pm.discount_percentage,
    pm.authenticity_score,
    pm.authenticity_confidence,
    pm.authenticity_red_flags
FROM items i
INNER JOIN product_metadata pm ON i.id = pm.item_id
WHERE pm.authenticity_score < 60
ORDER BY pm.authenticity_score ASC;

-- Verified Deals: High authenticity + good discount
CREATE OR REPLACE VIEW verified_deals AS
SELECT
    i.external_id AS item_id,
    i.title,
    i.price,
    pm.lens_brand,
    pm.lens_original_price,
    pm.discount_percentage,
    pm.authenticity_score
FROM items i
INNER JOIN product_metadata pm ON i.id = pm.item_id
WHERE pm.authenticity_score >= 80
  AND pm.discount_percentage >= 40
ORDER BY pm.discount_percentage DESC, pm.authenticity_score DESC;

-- Items Needing Enrichment: Unenriched products
CREATE OR REPLACE VIEW items_needing_enrichment AS
SELECT
    i.id,
    i.external_id AS item_id,
    i.title,
    i.price,
    i.image_url,
    CASE
        WHEN pm.id IS NULL THEN 'not_enriched'
        WHEN pm.lens_brand IS NULL THEN 'brand_missing'
        WHEN pm.lens_original_price IS NULL THEN 'price_missing'
        WHEN pm.authenticity_score IS NULL THEN 'authenticity_not_checked'
        ELSE 'complete'
    END AS enrichment_status
FROM items i
LEFT JOIN product_metadata pm ON i.id = pm.item_id
WHERE i.image_url IS NOT NULL
  AND (pm.id IS NULL OR pm.lens_brand IS NULL OR pm.lens_original_price IS NULL)
ORDER BY i.scraped_at DESC;

-- ================================================================================================
-- FUNCTIONS
-- ================================================================================================

-- Enrichment Completeness: Calculate product enrichment progress
CREATE OR REPLACE FUNCTION enrichment_completeness(item_id_param INTEGER)
RETURNS JSONB AS $$
DECLARE
    result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'has_lens_data', pm.lens_title IS NOT NULL,
        'has_brand', pm.lens_brand IS NOT NULL,
        'has_original_price', pm.lens_original_price IS NOT NULL,
        'has_materials', pm.materials IS NOT NULL,
        'has_authenticity_check', pm.authenticity_score IS NOT NULL,
        'completeness_score', (
            (CASE WHEN pm.lens_title IS NOT NULL THEN 20 ELSE 0 END) +
            (CASE WHEN pm.lens_brand IS NOT NULL THEN 20 ELSE 0 END) +
            (CASE WHEN pm.lens_original_price IS NOT NULL THEN 20 ELSE 0 END) +
            (CASE WHEN pm.materials IS NOT NULL THEN 20 ELSE 0 END) +
            (CASE WHEN pm.authenticity_score IS NOT NULL THEN 20 ELSE 0 END)
        )
    )
    INTO result
    FROM product_metadata pm
    WHERE pm.item_id = item_id_param;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ================================================================================================
-- TRIGGERS
-- ================================================================================================

-- Update product_metadata timestamp on modification
CREATE OR REPLACE FUNCTION update_product_metadata_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_product_metadata_timestamp ON product_metadata;

CREATE TRIGGER trigger_update_product_metadata_timestamp
    BEFORE UPDATE ON product_metadata
    FOR EACH ROW
    EXECUTE FUNCTION update_product_metadata_timestamp();

-- ================================================================================================
-- SCHEMA COMPLETE
-- ================================================================================================
