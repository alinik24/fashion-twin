# Fashion Twin

**AI-Powered Fashion Deal Hunter & Personal Shopping Assistant**

Automatically discovers underpriced luxury items on second-hand marketplaces and learns your style through RLHF. Dual-mode system: passive learning for personalized recommendations, or aggressive hunting for mass deal discovery and resale opportunities.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)

---

## Features

### 🎯 Intelligent Deal Discovery
- **Multi-factor scoring** (0-100): Price analysis (40%), price history (30%), condition (20%), time urgency (10%)
- **Smart price tracking**: Historical trends, drop detection, market averages
- **Premium brand bonuses**: Extra points for Chanel, Hermès, Gucci, Prada, Dior, Celine
- **Authenticity verification**: Google Lens-powered fake detection (0-100 score)
- **Real-time alerts**: Discord, Telegram, Email notifications

### 🧠 Personalized Learning
- **RLHF (Reinforcement Learning from Human Feedback)**: LLM judges items and learns from your preferences
- **Behavioral tracking**: Dwell time, clicks, offers, browsing patterns (GDPR-compliant)
- **FashionCLIP embeddings**: Visual similarity search with 512-dimensional vectors
- **Hybrid ranking**: Collaborative filtering + content-based + contextual bandits
- **Style profile evolution**: Automatic inference from your behavior + explicit rules

### 🔌 Complete Data Pipeline (50+ Sources)
Captures **every byte** that commercial platforms learn from:

**Official Data**
- ✓ GDPR export (favorites, purchases, messages, offers, browsing history)
- ✓ Account preferences and saved searches
- ✓ Chat negotiations and offer patterns

**Browser Data** (via [HackBrowserData](https://github.com/moonD4rk/HackBrowserData))
- ✓ Session cookies (auto-extraction, no manual copying!)
- ✓ Complete browsing history
- ✓ Download tracking
- ✓ Bookmark analysis

**Product Enrichment** (via [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr))
- ✓ Google Lens visual search
- ✓ Original manufacturer pages
- ✓ Material composition
- ✓ Retail price verification
- ✓ Authenticity red flags

**Scraping** (via [Crawlee](https://github.com/apify/crawlee))
- ✓ Production-grade reliability
- ✓ Auto-scaling concurrency
- ✓ Session management
- ✓ Retry logic & deduplication

### 🎨 Flexible AI Integration
- **Multiple providers**: OpenRouter (100+ models), External APIs (Azure/OpenAI/Claude), Local (Ollama)
- **Task-specific routing**: Different models for reward modeling, reasoning, fast inference
- **Open-source defaults**: Local FashionCLIP + Ollama LLaMA 3.1

### 🎭 Two Operating Modes

#### Regular Mode (Personal Shopping)
*Passive learning focused on your preferences*

- Learns from favorites, browsing, offers
- Builds personalized style profile
- Recommends items matching your taste
- GDPR-compliant behavioral tracking
- Perfect for: Finding your dream pieces

**Configuration:**
```yaml
mode: regular
pipelines:
  vinted_favorites: {enabled: true, weight: 1.0}
  vinted_searches: {enabled: true, weight: 0.8}
  browser_history: {enabled: true, weight: 0.6}
  gdpr_export: {enabled: true, weight: 1.5}  # Most complete data
```

#### Aggressive Mode (Mass Hunting)
*Active scanning for maximum deal discovery and resale*

- Continuous marketplace scanning
- Multi-category parallel search
- Real-time price tracking
- Profit margin calculation
- Market intelligence gathering
- Perfect for: Resellers, retailers, deal hunters

**Configuration:**
```yaml
mode: aggressive
scan_interval: 30min
max_concurrent: 10
pipelines:
  market_prices: {enabled: true, weight: 2.0}
  competitor_analysis: {enabled: true, weight: 1.5}
  price_history: {enabled: true, weight: 2.0}
  deal_hunting: {enabled: true, weight: 2.5}
categories: [jackets, dresses, bags, shoes, accessories]
min_deal_score: 70
alert_channels: [discord, telegram, email]
```

---

## Quick Start

### Prerequisites
- **Python 3.12** (or 3.10+)
- **Docker Desktop**
- **8GB+ RAM**

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/fashion_twin.git
cd fashion_twin

# Create virtual environment (Windows)
py -3.12 -m venv .venv
.\.venv\Scripts\Activate

# Or (Linux/Mac)
python3.12 -m venv .venv
source .venv/bin/activate

# Upgrade pip
python -m pip install --upgrade pip

# Install dependencies (~2GB download, 5-15 minutes)
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
```

### Database Setup

```bash
# Start all services (PostgreSQL + Qdrant + Redis)
docker compose up -d

# Verify services are running
docker compose ps

# Initialize database schema (automatic on first run)
python scripts/init_db.py
```

**What just happened?**
- PostgreSQL database created automatically
- Unified schema loaded (all tables, views, functions)
- Qdrant vector collection initialized
- Redis cache started

**Access database admin**: http://localhost:8081
- System: PostgreSQL
- Server: postgres
- Username: postgres
- Password: postgres
- Database: fashion_twin

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
# Minimum required (everything else has defaults):
#   POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/fashion_twin
#   LLM_PRIMARY_PROVIDER=openrouter (or api_provider, or local)
#   OPENROUTER_API_KEY=your-key-here (if using OpenRouter)
```

**Choose your mode:**

Regular Mode (.env):
```bash
HUNTER_MODE_ENABLED=false
RLHF_ENABLED=true
BEHAVIORAL_TRACKING=true
```

Aggressive Mode (.env):
```bash
HUNTER_MODE_ENABLED=true
HUNTER_SCAN_INTERVAL_MINUTES=30
HUNTER_MAX_PRICE=200
HUNTER_MIN_DEAL_SCORE=70
HUNTER_CATEGORIES=jackets,dresses,bags,shoes
HUNTER_PRIORITY_BRANDS=chanel,gucci,prada,hermes
```

### First Run

```bash
# 1. Set up your style profile
python scripts/manage_profile.py setup

# 2. (Optional) Add filtering rules
python scripts/manage_profile.py rules add \
  --field material \
  --operator not_contains \
  --value polyester \
  --type block

# 3. Scrape some items
python scripts/ingest_items.py --query "silk blouse" --pages 5

# 4. Enrich products with Google Lens
python scripts/enrich_products.py --all

# 5. Get recommendations
python scripts/recommend.py --query "silk blouse" --explain
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Fashion Twin System                       │
└─────────────────────────────────────────────────────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
        ┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼────────┐
        │ Data Pipelines│ │  ML Engine  │ │ Deal Hunter   │
        └───────┬──────┘ └──────┬──────┘ └──────┬────────┘
                │                │                │
    ┌───────────┼────────────────┼────────────────┼───────────┐
    │           │                │                │           │
┌───▼──┐ ┌─────▼────┐ ┌─────────▼────┐ ┌─────────▼──┐ ┌─────▼────┐
│ GDPR │ │ Browser  │ │ FashionCLIP  │ │ Price      │ │ Google   │
│Export│ │ HackData │ │ Embeddings   │ │ Tracker    │ │ Lens     │
└──────┘ └──────────┘ └──────────────┘ └────────────┘ └──────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              ┌─────▼─────┐ ┌───▼────┐ ┌────▼─────┐
              │PostgreSQL │ │Qdrant  │ │  Redis   │
              │(Items,    │ │(Vector │ │ (Cache)  │
              │Prefs,     │ │Search) │ │          │
              │Deals)     │ │        │ │          │
              └───────────┘ └────────┘ └──────────┘
```

**Core Components:**

- **`collector/`**: Marketplace scrapers (Vinted, Vestiaire, Depop)
- **`pipeline/`**: Data extractors (GDPR, browser, enrichment) & orchestration
- **`embedder/`**: FashionCLIP image embeddings
- **`ranker/`**: LightFM collaborative filtering + bandits
- **`rlhf/`**: Reward model + DPO training + preference learning
- **`deal_hunter/`**: Price tracking + deal scoring + alerts
- **`tracker/`**: Behavioral signals + consent management
- **`llm/`**: Multi-provider LLM client (OpenRouter, Azure, Local)
- **`storage/`**: PostgreSQL + Qdrant + Redis interfaces

---

## Data Pipelines

The system supports **50+ configurable data pipelines**. Configure in `config/pipeline_config.yaml`:

```yaml
pipelines:
  # Official Vinted data
  vinted_favorites:
    enabled: true
    weight: 1.0
    description: "Items you favorited"
  
  vinted_searches:
    enabled: true
    weight: 0.8
    description: "Your search history"
  
  vinted_offers:
    enabled: true
    weight: 1.2
    description: "Negotiation patterns from chat"
  
  # GDPR export (most complete official data)
  gdpr_export:
    enabled: true
    weight: 1.5
    description: "Full data export from Vinted"
    sources: [favorites, purchases, messages, browsing, offers]
  
  # Browser data (automatic extraction)
  browser_cookies:
    enabled: true
    weight: 0.5
    description: "Session cookies via HackBrowserData"
  
  browser_history:
    enabled: true
    weight: 0.6
    description: "Browsing patterns and frequency"
  
  # Product enrichment
  google_lens:
    enabled: true
    weight: 1.0
    description: "Visual search for product details"
  
  # Market intelligence (aggressive mode)
  price_tracking:
    enabled: false  # Auto-enabled in aggressive mode
    weight: 2.0
  
  competitor_listings:
    enabled: false  # Auto-enabled in aggressive mode
    weight: 1.5
```

### Import GDPR Export

1. **Request your data**: Vinted → Settings → Privacy → Download my data
2. **Wait 1-7 days** for email with download link
3. **Extract ZIP** to `data/gdpr_export/`
4. **Import**:
```bash
python scripts/import_vinted_gdpr.py \
  --export-dir ./data/gdpr_export \
  --import-all
```

Imports:
- ✓ Favorites & saved searches
- ✓ Purchase history
- ✓ Messages & offer negotiations
- ✓ Browsing history with timestamps
- ✓ Listing views and interactions
- ✓ Account preferences

### Auto-Extract Browser Data

```bash
# Install HackBrowserData
npm install -g hack-browser-data

# Extract from Chrome (auto-saves session cookie to .env!)
python scripts/import_browser_data.py --browser chrome --import

# Other browsers: firefox, edge, safari, opera
```

### Enrich Products with Google Lens

```bash
# Install chrome-lens-ocr
npm install -g chrome-lens-ocr

# Enrich all unenriched items
python scripts/enrich_products.py --all

# Batch enrich with parallel workers
python scripts/enrich_products.py --batch 100 --workers 10

# Check statistics
python scripts/enrich_products.py --stats

# List potential fakes
python scripts/enrich_products.py --list-fakes
```

---

## Deal Hunting

### Manual Hunt

```bash
# Hunt for deals in specific categories
python scripts/hunt_deals.py \
  --categories jackets dresses \
  --max-price 200 \
  --min-score 70 \
  --alert discord

# Results:
# Found 23 deals (8 excellent, 12 good, 3 fair)
# Top deal: Chanel jacket - £45 (87% off) - Score: 94/100
# Alerts sent to Discord
```

### Automatic Hunting (Aggressive Mode)

```bash
# Enable in .env:
HUNTER_MODE_ENABLED=true
HUNTER_SCAN_INTERVAL_MINUTES=30
HUNTER_MIN_DEAL_SCORE=70

# Run continuous hunter
python scripts/hunt_deals.py --continuous

# Scans every 30 minutes
# Sends alerts for deals >= 70 score
# Tracks price history
# Detects fakes
```

### Price Tracking

```bash
# Track specific items
python scripts/track_prices.py --item vinted_12345

# Get price history
python scripts/track_prices.py --history --days 30

# Alert on drops
PRICE_DROP_ALERT_THRESHOLD=0.15  # Alert if 15%+ drop
PRICE_DROP_MIN_AMOUNT=10.0       # And at least £10
```

---

## Personalization & RLHF

### Style Profile

```bash
# Interactive setup
python scripts/manage_profile.py setup

# Add preferences
python scripts/manage_profile.py add \
  --attribute preferred_color \
  --value navy \
  --strength 0.9

# Load preset rules
python scripts/manage_profile.py rules preset sustainable
python scripts/manage_profile.py rules preset luxury
```

### RLHF Training

```bash
# 1. Seed initial preferences (label 50-100 items)
python scripts/seed_preferences.py --count 100

# 2. Run full RLHF loop
python scripts/run_rlhf.py \
  --pairs 50 \
  --dpo-iterations 5 \
  --llm-judge

# Process:
# - LLM judges item pairs
# - Learns from your feedback
# - Updates reward model via DPO
# - Improves recommendations

# 3. Get personalized recommendations
python scripts/recommend.py \
  --query "vintage jacket" \
  --top 20 \
  --explain
```

---

## Development

### Project Structure

```
fashion_twin/
├── config/                    # Configuration
│   ├── settings.py           # Pydantic settings
│   └── pipeline_config.yaml  # Data pipeline configuration
├── storage/                   # Database
│   ├── schema.sql            # Unified schema (all tables)
│   ├── postgres.py           # PostgreSQL client
│   └── qdrant_store.py       # Vector database client
├── collector/                 # Marketplace scrapers
│   ├── vinted.py
│   ├── vestiaire.py
│   └── base.py
├── pipeline/                  # Data pipelines
│   ├── orchestrator.py       # Pipeline manager
│   ├── extractors/           # Data extractors
│   │   ├── gdpr_extractor.py
│   │   ├── hackbrowserdata_extractor.py
│   │   └── crawlee_extractor.py
│   └── enrichers/            # Data enrichment
│       └── google_lens_enricher.py
├── embedder/                  # FashionCLIP
│   └── fashion_clip.py
├── ranker/                    # Recommendation engine
│   ├── lightfm_model.py      # Collaborative filtering
│   ├── bandit.py             # Contextual bandits
│   └── train.py
├── rlhf/                      # Reinforcement learning
│   ├── reward_model.py
│   ├── dpo.py                # Direct Preference Optimization
│   └── feedback_loop.py
├── deal_hunter/               # Deal discovery
│   ├── hunter.py
│   ├── deal_scorer.py
│   ├── price_tracker.py
│   └── alert_system.py
├── tracker/                   # Behavioral tracking
│   ├── signals.py
│   ├── session.py
│   └── consent.py
├── llm/                       # LLM client
│   └── client.py             # Multi-provider (OpenRouter, Azure, Local)
├── scripts/                   # CLI tools
│   ├── init_db.py
│   ├── ingest_items.py
│   ├── enrich_products.py
│   ├── hunt_deals.py
│   ├── recommend.py
│   ├── run_rlhf.py
│   └── ...
└── tests/                     # Tests
    ├── test_storage.py
    ├── test_ranker.py
    └── ...
```

### Running Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Specific test
pytest tests/test_storage.py -v
```

### Database Schema

Single unified schema with:
- **Core tables**: items, interactions, embeddings
- **Behavioral tracking**: signals, sessions, consent
- **RLHF**: preference_comparisons, reward_scores, style_profile
- **Deal hunting**: price_history, deals_found, market_averages
- **Enrichment**: product_metadata (Google Lens)
- **Views**: best_deals, potential_fakes, verified_deals
- **Functions**: enrichment_completeness()

View schema: `cat storage/schema.sql`

---

## Deployment

### Docker Compose (Production)

```bash
# Production deployment
docker compose -f docker-compose.prod.yml up -d

# With monitoring
docker compose -f docker-compose.prod.yml -f docker-compose.monitoring.yml up -d
```

### Environment Variables

All configuration via `.env`:
- Database connections
- API keys (OpenRouter, Azure, etc.)
- Mode selection (regular vs aggressive)
- Feature flags
- Performance tuning

See `.env.example` for full reference.

---

## Troubleshooting

### Database Connection Issues

```bash
# Check services
docker compose ps

# Restart PostgreSQL
docker compose restart postgres

# View logs
docker compose logs postgres

# Connect manually
docker exec -it fashion_twin_postgres psql -U postgres -d fashion_twin
```

### Scraping Rate Limits

```bash
# Add delays in .env
SCRAPE_DELAY_MIN=2.0
SCRAPE_DELAY_MAX=5.0

# Use proxies
SCRAPE_PROXIES=http://proxy1:8080,http://proxy2:8080

# Rotate user agents
SCRAPE_ROTATE_USER_AGENTS=true
```

### Memory Issues

```bash
# Reduce batch sizes
EMBEDDING_BATCH_SIZE=16
LIGHTFM_NUM_THREADS=2

# Limit concurrent operations
HUNTER_MAX_CONCURRENT=5
```

---

## Proven Open-Source Components

This project integrates battle-tested open-source solutions:

- **[chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr)**: Google Lens visual search
- **[HackBrowserData](https://github.com/moonD4rk/HackBrowserData)**: Browser data extraction
- **[Crawlee](https://github.com/apify/crawlee)**: Production web scraping
- **[Qdrant](https://github.com/qdrant/qdrant)**: Vector similarity search
- **[LightFM](https://github.com/lyst/lightfm)**: Hybrid recommendation system
- **[FashionCLIP](https://github.com/patrickjohncyh/fashion-clip)**: Fashion-specific vision model

---

## License

MIT License - see LICENSE file for details.

---

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

---

## Acknowledgments

- FashionCLIP team for the vision model
- LightFM creators for collaborative filtering
- Qdrant for vector search
- All open-source contributors

---

**Built with ❤️ for fashion enthusiasts and deal hunters**
