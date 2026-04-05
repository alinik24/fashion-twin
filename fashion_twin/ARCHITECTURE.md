# Fashion Twin - System Architecture

Complete technical architecture for the AI-powered fashion recommendation and deal hunting system.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Fashion Twin Platform                         │
│                  Dual-Mode: Regular | Aggressive                     │
└─────────────────────────────────────────────────────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
      ┌───────▼──────┐    ┌──────▼──────┐    ┌──────▼────────┐
      │ Data         │    │ ML/AI       │    │ Deal          │
      │ Pipelines    │    │ Engine      │    │ Hunter        │
      └───────┬──────┘    └──────┬──────┘    └──────┬────────┘
              │                   │                   │
              └───────────────────┼───────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │    Storage Layer          │
                    │ PostgreSQL | Qdrant | Redis │
                    └───────────────────────────┘
```

---

## Component Architecture

### 1. Data Pipelines Layer

**Purpose**: Extract, transform, and load data from multiple sources

#### 1.1 Official Data Extractors
```
┌─────────────────────────────────────────────────────────┐
│ GDPR Export Extractor                                   │
│ Path: pipeline/extractors/gdpr_extractor.py            │
│                                                         │
│ Sources:                                                │
│  - Favorites, purchases, messages                       │
│  - Browsing history, offers                             │
│  - Listings, analytics                                  │
│                                                         │
│ Output: PostgreSQL (interactions, behavior_signals)     │
└─────────────────────────────────────────────────────────┘
```

#### 1.2 Browser Data Extractors
```
┌─────────────────────────────────────────────────────────┐
│ HackBrowserData Extractor                               │
│ Path: pipeline/extractors/hackbrowserdata_extractor.py │
│ GitHub: github.com/moonD4rk/HackBrowserData            │
│                                                         │
│ Extracts:                                               │
│  - Session cookies (auto-saved to .env)                 │
│  - Complete browsing history                            │
│  - Download tracking                                    │
│  - Bookmarks                                            │
│                                                         │
│ Output: PostgreSQL (behavior_signals, activity_log)     │
└─────────────────────────────────────────────────────────┘
```

#### 1.3 Web Scraping
```
┌─────────────────────────────────────────────────────────┐
│ Crawlee-based Marketplace Scraper                       │
│ Path: pipeline/extractors/crawlee_extractor.py         │
│ GitHub: github.com/apify/crawlee                        │
│                                                         │
│ Features:                                               │
│  - Auto-scaling concurrency                             │
│  - Session management                                   │
│  - Retry logic & deduplication                          │
│  - Production-grade reliability                         │
│                                                         │
│ Output: PostgreSQL (items, price_history)               │
└─────────────────────────────────────────────────────────┘
```

#### 1.4 Product Enrichment
```
┌─────────────────────────────────────────────────────────┐
│ Google Lens Enricher                                    │
│ Path: pipeline/enrichers/google_lens_enricher.py       │
│ Tool: chrome-lens-ocr                                   │
│ GitHub: github.com/dimdenGD/chrome-lens-ocr            │
│                                                         │
│ Process:                                                │
│  1. Visual search via Google Lens                       │
│  2. Find original manufacturer pages                    │
│  3. Extract: brand, model, materials, retail price      │
│  4. Authenticity scoring (0-100)                        │
│  5. Detect red flags                                    │
│                                                         │
│ Output: PostgreSQL (product_metadata)                   │
└─────────────────────────────────────────────────────────┘
```

#### 1.5 Pipeline Orchestrator
```
┌─────────────────────────────────────────────────────────┐
│ Pipeline Orchestrator                                   │
│ Path: pipeline/orchestrator.py                          │
│ Config: config/pipeline_config.yaml                     │
│                                                         │
│ Responsibilities:                                       │
│  - Load pipeline configuration                          │
│  - Execute enabled pipelines                            │
│  - Apply weights                                        │
│  - Trigger ML retraining                                │
│  - Mode switching (regular <-> aggressive)              │
└─────────────────────────────────────────────────────────┘
```

---

### 2. ML/AI Engine

#### 2.1 Embedding Layer
```
┌─────────────────────────────────────────────────────────┐
│ FashionCLIP Embedder                                    │
│ Path: embedder/fashion_clip.py                          │
│ Model: patrickjohncyh/fashion-clip                      │
│ GitHub: github.com/patrickjohncyh/fashion-clip         │
│                                                         │
│ Features:                                               │
│  - 512-dimensional image embeddings                     │
│  - Fashion-specific vision model                        │
│  - CPU/GPU support                                      │
│  - Batch processing                                     │
│                                                         │
│ Output: Qdrant (vector search)                          │
└─────────────────────────────────────────────────────────┘
```

#### 2.2 Ranking System
```
┌─────────────────────────────────────────────────────────┐
│ LightFM Collaborative Filtering                         │
│ Path: ranker/lightfm_model.py                           │
│ GitHub: github.com/lyst/lightfm                         │
│                                                         │
│ Algorithm: WARP (Weighted Approximate-Rank Pairwise)    │
│ Features: Hybrid (collaborative + content)              │
│                                                         │
│ Input: interactions, item_features, user_features       │
│ Output: Ranked recommendations                          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Contextual Bandits                                      │
│ Path: ranker/bandit.py                                  │
│                                                         │
│ Algorithm: Thompson Sampling                            │
│ Purpose: Online learning, exploration-exploitation      │
└─────────────────────────────────────────────────────────┘
```

#### 2.3 RLHF System
```
┌─────────────────────────────────────────────────────────┐
│ Reward Model + DPO Training                             │
│ Path: rlhf/                                             │
│                                                         │
│ Components:                                             │
│  ┌─────────────────────────────────────────┐            │
│  │ Reward Model (reward_model.py)          │            │
│  │ - Scores items 0-10                     │            │
│  │ - Style match + trend align + rules     │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│  ┌─────────────────────────────────────────┐            │
│  │ DPO Training (dpo.py)                   │            │
│  │ - Direct Preference Optimization        │            │
│  │ - No explicit reward model needed       │            │
│  │ - Reference: Rafailov et al. (2023)     │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│  ┌─────────────────────────────────────────┐            │
│  │ Feedback Loop (feedback_loop.py)        │            │
│  │ - Collect preferences                   │            │
│  │ - LLM judge auto-labeling               │            │
│  │ - Trigger DPO updates                   │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│ Input: preference_comparisons (PostgreSQL)              │
│ Output: Updated reward model weights                    │
└─────────────────────────────────────────────────────────┘
```

#### 2.4 LLM Client
```
┌─────────────────────────────────────────────────────────┐
│ Multi-Provider LLM Client                               │
│ Path: llm/client.py                                     │
│                                                         │
│ Providers:                                              │
│  ┌────────────────────────────────────┐                 │
│  │ OpenRouter                         │                 │
│  │ - 100+ models                      │                 │
│  │ - Task-specific routing            │                 │
│  └────────────────────────────────────┘                 │
│                                                         │
│  ┌────────────────────────────────────┐                 │
│  │ External API Providers             │                 │
│  │ - Azure OpenAI, OpenAI, Claude     │                 │
│  │ - Configurable endpoint            │                 │
│  └────────────────────────────────────┘                 │
│                                                         │
│  ┌────────────────────────────────────┐                 │
│  │ Local (Ollama)                     │                 │
│  │ - LLaMA 3.1, Mistral               │                 │
│  │ - Fully open-source                │                 │
│  └────────────────────────────────────┘                 │
│                                                         │
│ Task Routing:                                           │
│  - Reward model: Claude/GPT                             │
│  - Fast inference: LLaMA 70B                            │
│  - Reasoning: Claude                                    │
│  - Deal analysis: LLaMA 70B                             │
└─────────────────────────────────────────────────────────┘
```

---

### 3. Deal Hunter

```
┌─────────────────────────────────────────────────────────┐
│ Deal Hunter System                                      │
│ Path: deal_hunter/                                      │
│                                                         │
│ ┌─────────────────────────────────────────┐             │
│ │ hunter.py - Main Hunter Loop            │             │
│ │  - Continuous scanning                  │             │
│ │  - Multi-category parallel search       │             │
│ │  - Mode: continuous or manual           │             │
│ └─────────────────────────────────────────┘             │
│                                                         │
│ ┌─────────────────────────────────────────┐             │
│ │ deal_scorer.py - Deal Scoring           │             │
│ │  - Price analysis (40%)                 │             │
│ │  - Price history (30%)                  │             │
│ │  - Condition (20%)                      │             │
│ │  - Time urgency (10%)                   │             │
│ │  - Premium brand bonuses                │             │
│ └─────────────────────────────────────────┘             │
│                                                         │
│ ┌─────────────────────────────────────────┐             │
│ │ price_tracker.py - Price Tracking       │             │
│ │  - Historical data collection           │             │
│ │  - Drop detection                       │             │
│ │  - Market averages                      │             │
│ │  - Trend analysis                       │             │
│ └─────────────────────────────────────────┘             │
│                                                         │
│ ┌─────────────────────────────────────────┐             │
│ │ alert_system.py - Notifications         │             │
│ │  - Discord webhooks                     │             │
│ │  - Telegram bot                         │             │
│ │  - Email alerts                         │             │
│ └─────────────────────────────────────────┘             │
│                                                         │
│ Output: deals_found, price_alerts (PostgreSQL)          │
└─────────────────────────────────────────────────────────┘
```

---

### 4. Storage Layer

#### 4.1 PostgreSQL Database
```
┌─────────────────────────────────────────────────────────┐
│ PostgreSQL Database                                     │
│ Container: fashion_twin_postgres                        │
│ Port: 5432                                              │
│ Schema: storage/schema.sql (unified)                    │
│                                                         │
│ Core Tables:                                            │
│  - items (scraped listings)                             │
│  - interactions (user feedback)                         │
│  - item_embeddings (Qdrant pointers)                    │
│  - model_snapshots (trained models)                     │
│  - scrape_jobs (audit log)                              │
│                                                         │
│ Behavioral Tracking:                                    │
│  - behavior_signals (implicit feedback)                 │
│  - tracker_sessions (browsing sessions)                 │
│  - consent_log (GDPR compliance)                        │
│  - activity_log (general activity)                      │
│                                                         │
│ RLHF:                                                   │
│  - preference_comparisons (pairwise)                    │
│  - reward_scores (cached scores)                        │
│  - style_profile (inferred + explicit)                  │
│  - user_rules (filters)                                 │
│  - trends (external data)                               │
│  - dpo_training_log (DPO history)                       │
│                                                         │
│ Deal Hunting:                                           │
│  - price_history (historical prices)                    │
│  - price_alerts (drop notifications)                    │
│  - deals_found (discovered deals)                       │
│  - hunter_scans (scan sessions)                         │
│  - market_averages (benchmarks)                         │
│                                                         │
│ Product Enrichment:                                     │
│  - product_metadata (Google Lens data)                  │
│                                                         │
│ Views:                                                  │
│  - price_trends, best_deals, daily_deal_stats          │
│  - items_with_metadata, potential_fakes                │
│  - verified_deals, items_needing_enrichment            │
└─────────────────────────────────────────────────────────┘
```

#### 4.2 Qdrant Vector Database
```
┌─────────────────────────────────────────────────────────┐
│ Qdrant Vector Database                                  │
│ Container: fashion_twin_qdrant                          │
│ Port: 6333 (HTTP), 6334 (gRPC)                          │
│ GitHub: github.com/qdrant/qdrant                        │
│                                                         │
│ Collection: fashion_items                               │
│  - Dimension: 512 (FashionCLIP)                         │
│  - Distance: Cosine similarity                          │
│                                                         │
│ Operations:                                             │
│  - Image similarity search                              │
│  - Batch upsert (embeddings)                            │
│  - Filtering by metadata                                │
│                                                         │
│ Client: storage/qdrant_store.py                         │
└─────────────────────────────────────────────────────────┘
```

#### 4.3 Redis Cache
```
┌─────────────────────────────────────────────────────────┐
│ Redis Cache                                             │
│ Container: fashion_twin_redis                           │
│ Port: 6379                                              │
│                                                         │
│ Use Cases:                                              │
│  - Price tracking cache                                 │
│  - Deal score cache (TTL: 1 hour)                       │
│  - Session data                                         │
│  - Rate limiting counters                               │
│  - Task queue (background jobs)                         │
└─────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Regular Mode (Personal Shopping)
```
User browses Vinted
        │
        ▼
┌───────────────┐
│ Browser       │ → HackBrowserData → behavior_signals
│ Activity      │
└───────────────┘
        │
        ▼
┌───────────────┐
│ User Exports  │ → GDPR Extractor → interactions
│ GDPR Data     │
└───────────────┘
        │
        ▼
┌───────────────┐
│ Items Scraped │ → Vinted Scraper → items
└───────────────┘
        │
        ▼
┌───────────────┐
│ FashionCLIP   │ → Embeddings → Qdrant
│ Processing    │
└───────────────┘
        │
        ▼
┌───────────────┐
│ LightFM       │ → Training → Recommendations
│ + Bandits     │
└───────────────┘
        │
        ▼
┌───────────────┐
│ RLHF Loop     │ → Feedback → Improved Recommendations
└───────────────┘
```

### Aggressive Mode (Mass Hunting)
```
Continuous Scan Trigger (every 30 min)
        │
        ▼
┌───────────────┐
│ Hunter        │ → Multi-category → items
│ Parallel Scan │    scraping
└───────────────┘
        │
        ▼
┌───────────────┐
│ Google Lens   │ → Enrichment → product_metadata
│ Enrichment    │
└───────────────┘
        │
        ▼
┌───────────────┐
│ Price         │ → Historical → price_history
│ Tracking      │    data
└───────────────┘
        │
        ▼
┌───────────────┐
│ Deal          │ → Scoring → deals_found
│ Scoring       │    (0-100)
└───────────────┘
        │
        ▼
┌───────────────┐
│ Alert         │ → Discord/Telegram/Email
│ System        │
└───────────────┘
```

---

## Deployment Architecture

### Development (Local)
```
┌─────────────────────────────────────────────────────────┐
│ Docker Compose (docker-compose.yml)                     │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ PostgreSQL  │  │   Qdrant    │  │   Redis     │     │
│  │   :5432     │  │ :6333/:6334 │  │   :6379     │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
│                                                         │
│  ┌─────────────┐                                        │
│  │  Adminer    │  Database admin UI                     │
│  │   :8081     │                                        │
│  └─────────────┘                                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Python Application (local venv)                         │
│  - All scripts and modules                              │
│  - Connects to Docker services                          │
└─────────────────────────────────────────────────────────┘
```

### Production
```
┌─────────────────────────────────────────────────────────┐
│ Kubernetes / Docker Swarm                               │
│                                                         │
│  ┌──────────────────────────────────────┐               │
│  │ Application Pods                     │               │
│  │  - API Server                        │               │
│  │  - Background Workers                │               │
│  │  - Hunter Scheduler                  │               │
│  └──────────────────────────────────────┘               │
│                                                         │
│  ┌──────────────────────────────────────┐               │
│  │ Databases (StatefulSets)             │               │
│  │  - PostgreSQL (persistent volume)    │               │
│  │  - Qdrant (persistent volume)        │               │
│  │  - Redis (persistent volume)         │               │
│  └──────────────────────────────────────┘               │
│                                                         │
│  ┌──────────────────────────────────────┐               │
│  │ Monitoring                           │               │
│  │  - Prometheus (metrics)              │               │
│  │  - Grafana (dashboards)              │               │
│  │  - Sentry (error tracking)           │               │
│  └──────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────┘
```

---

## External Services & APIs

```
┌─────────────────────────────────────────────────────────┐
│ LLM Providers                                           │
│  - OpenRouter (100+ models)                             │
│  - External API (Azure OpenAI, OpenAI, Claude, etc.)    │
│  - Ollama (local)                                       │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Marketplaces                                            │
│  - Vinted (primary)                                     │
│  - Vestiaire Collective                                 │
│  - Depop                                                │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Notification Channels                                   │
│  - Discord (webhooks)                                   │
│  - Telegram (bot API)                                   │
│  - Email (SMTP)                                         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Trend Sources                                           │
│  - Vogue                                                │
│  - Lyst                                                 │
│  - Pinterest                                            │
│  - WGSN                                                 │
└─────────────────────────────────────────────────────────┘
```

---

## Configuration Management

```
┌─────────────────────────────────────────────────────────┐
│ Configuration Files                                     │
│                                                         │
│  .env                    Environment variables          │
│  │  - API keys                                          │
│  │  - Database URLs                                     │
│  │  - Mode selection                                    │
│  │  - Feature flags                                     │
│                                                         │
│  config/pipeline_config.yaml                            │
│  │  - Pipeline enablement                               │
│  │  - Weights                                           │
│  │  - Mode-specific settings                            │
│                                                         │
│  config/settings.py      Pydantic settings              │
│  │  - Type-safe configuration                           │
│  │  - Validation                                        │
│  │  - Defaults                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Security & Privacy

```
┌─────────────────────────────────────────────────────────┐
│ GDPR Compliance                                         │
│  - Consent tracking (consent_log)                       │
│  - Data retention policies                              │
│  - Right to deletion                                    │
│  - Data export                                          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Security Measures                                       │
│  - API keys in .env (not committed)                     │
│  - Database credentials rotated                         │
│  - Rate limiting (Redis)                                │
│  - Input validation (Pydantic)                          │
│  - No sensitive data in logs                            │
└─────────────────────────────────────────────────────────┘
```

---

## Performance Optimization

```
┌─────────────────────────────────────────────────────────┐
│ Caching Strategy                                        │
│  - Redis: Deal scores (1 hour TTL)                      │
│  - Redis: Price data (6 hour TTL)                       │
│  - PostgreSQL: Materialized views (price_trends)        │
│  - Qdrant: Vector cache                                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Batch Processing                                        │
│  - Embedding generation: Batch size 32                  │
│  - Google Lens enrichment: Parallel workers 5           │
│  - Price tracking: Batch updates every 6 hours          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Database Indexing                                       │
│  - B-tree: id, item_id, user_id, created_at             │
│  - GiST: JSONB columns (raw_data, context)              │
│  - Partial: WHERE active = TRUE (style_profile)         │
└─────────────────────────────────────────────────────────┘
```

---

## Monitoring & Observability

```
┌─────────────────────────────────────────────────────────┐
│ Metrics                                                 │
│  - Items scraped per hour                               │
│  - Deals found per scan                                 │
│  - RLHF accuracy over time                              │
│  - API response times                                   │
│  - Database query performance                           │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Logging                                                 │
│  - Structured JSON logs                                 │
│  - Log levels: DEBUG, INFO, WARNING, ERROR              │
│  - Slow query logging (>1000ms)                         │
│  - Error tracking (Sentry)                              │
└─────────────────────────────────────────────────────────┘
```

---

## Scalability Considerations

```
┌─────────────────────────────────────────────────────────┐
│ Horizontal Scaling                                      │
│  - Stateless application servers                        │
│  - Database read replicas                               │
│  - Qdrant cluster mode                                  │
│  - Redis Sentinel for HA                                │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Vertical Scaling                                        │
│  - PostgreSQL: 8GB+ RAM                                 │
│  - Qdrant: 16GB+ RAM for large collections             │
│  - Application: 4GB+ RAM                                │
└─────────────────────────────────────────────────────────┘
```

---

## Technology Stack Summary

| Component | Technology | GitHub |
|-----------|-----------|--------|
| **Language** | Python 3.12+ | |
| **Web Framework** | (Future: FastAPI) | |
| **Database** | PostgreSQL 16 | |
| **Vector DB** | Qdrant | github.com/qdrant/qdrant |
| **Cache** | Redis 7 | |
| **Vision Model** | FashionCLIP | github.com/patrickjohncyh/fashion-clip |
| **Rec System** | LightFM | github.com/lyst/lightfm |
| **LLM Client** | Custom Multi-Provider | |
| **Web Scraping** | Crawlee | github.com/apify/crawlee |
| **Browser Data** | HackBrowserData | github.com/moonD4rk/HackBrowserData |
| **Product Search** | chrome-lens-ocr | github.com/dimdenGD/chrome-lens-ocr |
| **Containerization** | Docker Compose | |
| **Testing** | pytest | |

---

This architecture is designed for:
- **Scalability**: Horizontal and vertical scaling
- **Modularity**: Clean separation of concerns
- **Reliability**: Production-grade components
- **Privacy**: GDPR-compliant behavioral tracking
- **Performance**: Caching, batching, indexing
- **Flexibility**: Multi-mode operation (Regular/Aggressive)
