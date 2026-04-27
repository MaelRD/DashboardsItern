# Odoo Financial Intelligence: Scalable Liquidity Dashboard

> **Real-time financial visibility for decision-makers — powered by Odoo 18, Python & Dash.**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Dash](https://img.shields.io/badge/Dash-2.17+-00A8E0?style=flat-square&logo=plotly&logoColor=white)
![Plotly](https://img.shields.io/badge/Plotly-5.22+-3F4F75?style=flat-square&logo=plotly&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-2.2+-150458?style=flat-square&logo=pandas&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap-FLATLY-7952B3?style=flat-square&logo=bootstrap&logoColor=white)

---

## 🎯 Project Mission

Most ERP systems store valuable financial data — but bury it behind slow reports and fragmented modules. **This project solves that.**

The Odoo Financial Intelligence Dashboard transforms raw transactional data from Odoo 18 into **actionable, real-time financial insights** for CFOs, controllers, and business owners. Instead of waiting for monthly reports, decision-makers get:

- Live cash position across all bank and cash accounts
- Overdue invoice aging broken into risk buckets
- Forward-looking cash runway projections with scenario simulation
- Collection velocity trends and client concentration risk

The result: **faster decisions, less exposure, and full financial clarity — in a single screen.**

---

## 🏗️ Architecture — The Engineer's View

The application follows a **strict three-layer decoupled architecture** that separates concerns, isolates credentials, and enables swapping data sources without touching business logic or UI.

```
┌─────────────────────────────────────────────────────────────────┐
│                         ODOO 18 (ERP)                           │
│              account.move · account.payment · account.journal    │
└────────────────────────────┬────────────────────────────────────┘
                             │  XML-RPC API (port 443 / HTTPS)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 1 — EXTRACTION                         │
│                       extraction.py                             │
│  · OdooConnector: two-step XML-RPC auth, lazy proxy, domain     │
│    filters pushed server-side to minimize data transfer         │
│  · DemoDataGenerator: identical interface, seed=42, no Odoo     │
│  · get_data_source(): single factory — Odoo or Demo, with       │
│    automatic graceful fallback on auth failure                  │
└────────────────────────────┬────────────────────────────────────┘
                             │  dict[str, pd.DataFrame]
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  LAYER 2 — ANALYTICS ENGINE                     │
│                        analytics.py                             │
│  · Staging layer: vectorized Pandas transforms (np.select),     │
│    computed once per load — callbacks only read, never mutate   │
│  · KPI calculators: DSO, Burn Rate, Cash Runway, Liquidity      │
│    Ratio, Collection Rate                                        │
│  · Report builders: Aging, Monthly Comparison, Waterfall,       │
│    Client Concentration, DSO Velocity, Journal Breakdown        │
│  · What-if engine: cashflow projection with ±15% confidence     │
│    band + parameterized cobrabilidad (% collection rate)        │
└────────────────────────────┬────────────────────────────────────┘
                             │  KPIs + DataFrames (chart-ready)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   LAYER 3 — DASHBOARD UI                        │
│                        dashboard.py                             │
│  · Dash + Plotly: 7 interactive charts, 5 KPI cards            │
│  · Bootstrap FLATLY theme via dash-bootstrap-components         │
│  · Callback 1: full ETL + static charts (on load / refresh)    │
│  · Callback 2: What-if only (slider change — no ETL re-run)    │
│  · DataTable: critical invoices with conditional risk styling   │
└─────────────────────────────────────────────────────────────────┘
```

**Why this matters architecturally:**

| Concern | How it's solved |
|---|---|
| **Security** | Credentials live only in `.env` — never in code, never in Layer 2 or 3 |
| **Scalability** | Swap Odoo → PostgreSQL direct → any source by replacing Layer 1 only |
| **Performance** | Server-side domain filters on Odoo; staging computed once; callbacks read-only |
| **Resilience** | Auth failure → automatic Demo mode; dashboard never crashes |
| **Testability** | `DemoDataGenerator` provides identical interface — unit tests need no Odoo instance |

---

## ⚙️ Key Technical Features

### 🔄 Automated Data Pipeline

Efficient extraction using Odoo's `execute_kw('search_read')` with **server-side domain filters** — only relevant records are transmitted, not the full dataset.

```python
domain = [
    ["move_type", "in", ["out_invoice", "in_invoice"]],
    ["state",     "=",  "posted"],
    ["invoice_date", ">=", corte],   # server filters before transmitting
]
```

Models extracted: `account.move`, `account.payment`, `account.journal`

Two-step authentication handles both numeric UID and email/login credentials — compatible with Odoo SaaS and On-Premise deployments.

---

### 📊 Financial Engine

Core KPIs computed from the staging layer:

| KPI | Formula | Thresholds |
|---|---|---|
| **DSO** (Days Sales Outstanding) | `(CxC pendiente / Facturación anualizada) × 365` | ✅ <45d · ⚠️ 45-60d · 🔴 >60d |
| **Burn Rate** | `Avg monthly outbound payments (3-month rolling)` | — |
| **Cash Runway** | `Liquid balance / Burn Rate` | ✅ >6mo · ⚠️ 3-6mo · 🔴 <3mo |
| **Liquidity Ratio** | `Liquid balance / Monthly burn` | ✅ >1.5 · ⚠️ 1.0-1.5 · 🔴 <1.0 |
| **Collection Rate** | `Collected / Total invoiced (last 90d)` | — |

Aging report buckets: **Por vencer · 1-30d · 31-60d · 61-90d · +90d**

Each KPI returns a Bootstrap color code (`success` / `warning` / `danger`) for direct conditional UI rendering — no logic leaks into the dashboard layer.

---

### 🔮 Predictive Simulations — What-If Engine

The **cobrabilidad slider** (0–100%) drives a real-time cash projection model without re-running the ETL pipeline:

```
Projected Cash = Current Balance
              + (Pending AR × cobrabilidad%)
              - (Projected expenses × days)
```

The projection includes a **±15% confidence band** (optimistic / pessimistic scenarios) rendered as a shaded area chart. Decision-makers can immediately see:

- How many months of runway at different collection rates
- The dollar impact of a 10% drop in collections
- Break-even collection rate for maintaining positive cash position

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Data Source** | Odoo 18 XML-RPC API | ERP financial data |
| **ETL** | `xmlrpc.client` (stdlib) | Zero-dependency Odoo connector |
| **Data Processing** | **Pandas 2.2+** · NumPy | Staging, transforms, KPIs |
| **Web Framework** | **Dash 2.17+** | Reactive UI with Python callbacks |
| **Visualization** | **Plotly 5.22+** | 7 interactive chart types |
| **UI Components** | **dash-bootstrap-components** (FLATLY) | Professional layout & styling |
| **Configuration** | **python-dotenv** | Secure credential management |
| **Typography** | Inter · JetBrains Mono (Google Fonts) | Readable financial data display |
| **Production** | Gunicorn | WSGI server for deployment |

---

## 🚀 Installation & Setup

### Prerequisites

- Python 3.10+
- Access to an Odoo 18 instance (or use `DEMO_MODE=true` for local development)

### 1. Clone & create environment

```bash
git clone https://github.com/your-username/odoo-financial-dashboard.git
cd odoo-financial-dashboard

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` with your Odoo credentials:

```dotenv
# Odoo connection
ODOO_URL=https://your-company.odoo.com
ODOO_DB=your-database-name
ODOO_UID=your@email.com          # email or numeric UID — both supported
ODOO_PWD=your_api_key_here       # Settings → Users → Security → Generate API Key

# Set to true for development without an Odoo instance
DEMO_MODE=true
```

> **Where to find your credentials in Odoo 18:**
> - **ODOO_DB**: Settings → Activate Developer Mode → visible in URL
> - **ODOO_UID**: Settings → Users → your user → ID in the URL bar
> - **ODOO_PWD**: Settings → Users → your user → Security tab → Generate API Key

### 3. Run the dashboard

```bash
python dashboard.py
```

Open `http://localhost:8050` in your browser.

### 4. Production deployment (Gunicorn)

```bash
gunicorn dashboard:server -w 4 -b 0.0.0.0:8050 --timeout 120
```

---

## 🔒 Security First

**Credentials are never stored in code.** All sensitive values (`ODOO_URL`, `ODOO_DB`, `ODOO_UID`, `ODOO_PWD`) are loaded exclusively from environment variables via `python-dotenv`.

```
.env          ← local development only — NEVER commit this file
.env.example  ← safe template committed to the repo (no real values)
.gitignore    ← .env is listed here
```

In production (cloud / container deployments), inject variables directly into the environment — no `.env` file on the server:

```bash
# Docker
docker run -e ODOO_URL=... -e ODOO_PWD=... your-image

# Railway / Render / Fly.io
# Set via dashboard environment variable settings — no file needed
```

The `OdooConnector` is the **only layer** that ever reads credentials. `analytics.py` and `dashboard.py` receive clean DataFrames — they have no knowledge of the data source, URL, or authentication mechanism.

---

## 💡 Why It Matters

This project demonstrates the full stack of skills required for **enterprise-grade data engineering and financial software development**:

**System Integration** — Connecting to a live ERP (Odoo 18) via its XML-RPC API, handling authentication edge cases (email vs. numeric UID, SaaS vs. On-Premise), and implementing graceful fallback strategies when connectivity fails.

**Software Architecture** — A deliberately decoupled three-layer design where changing the data source requires touching exactly one file, and where the UI layer is completely agnostic to where data comes from.

**Financial Domain Knowledge** — Implementing CFO-level KPIs (DSO, Burn Rate, Cash Runway, Aging Buckets) correctly, with industry-standard thresholds and directionally accurate predictive models.

**Full-Stack Python Development** — From raw XML-RPC calls and vectorized Pandas transforms to reactive Dash callbacks and a professional Bootstrap UI — the entire application is Python, with no JavaScript written by hand.

**Production Readiness** — Structured logging, environment-based configuration, WSGI deployment, and a demo mode that makes the system demonstrable without external dependencies.

> *The gap between a working script and a production-ready data application is architecture. This project bridges that gap.*

---

## 📁 Project Structure

```
odoo-financial-dashboard/
├── extraction.py        # Layer 1: Odoo XML-RPC connector + Demo data generator
├── analytics.py         # Layer 2: KPI engine + report builders (staging layer)
├── dashboard.py         # Layer 3: Dash app, layout, callbacks, charts
├── assets/
│   └── style.css        # Custom CSS — Bootstrap overrides, typography, animations
├── requirements.txt     # Python dependencies
├── .env.example         # Credential template (safe to commit)
├── .env                 # Real credentials — NEVER commit
└── README.md
```

---

<div align="center">

**Built with precision. Deployed with confidence.**

*Odoo Financial Intelligence Dashboard — Portfolio Project*

</div>
