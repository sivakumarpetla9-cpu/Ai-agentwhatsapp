# WhatsApp Dine-In Restaurant Ordering Platform (Backend V1)

A production-oriented backend foundation for a multi-tenant WhatsApp Dine-In Restaurant Ordering Platform.

---

## 📖 Business Flow

Customers are physically inside the restaurant. Ordering is initiated in one of two ways:

- **Flow A (Table QR)**: Customer scans the table QR code (identifying restaurant & table) $\rightarrow$ WhatsApp opens $\rightarrow$ Menu is presented. (Customer never types table number).
- **Flow B (Restaurant WhatsApp Number)**: Customer messages the restaurant directly $\rightarrow$ Interactive table-selection interface $\rightarrow$ Table selected $\rightarrow$ Menu is presented.

Both flows proceed through:
**Menu $\rightarrow$ Category $\rightarrow$ Food Item $\rightarrow$ Quantity $\rightarrow$ Cart $\rightarrow$ Order Created $\rightarrow$ Kitchen Workflow (Accept $\rightarrow$ Preparing $\rightarrow$ Ready $\rightarrow$ Served)**.

---

## 🏛 Architecture

Strict separation of concerns:

```text
API routes (/api/v1)
        ↓
    Schemas (Pydantic v2)
        ↓
   Services (Business Logic)
        ↓
 Repositories (Data Access)
        ↓
PostgreSQL 16 (SQLAlchemy 2.0 Async / asyncpg)
```

- **Integrations Boundary (`app/integrations/`)**: External services (such as future WhatsApp Cloud API) live here, completely decoupled from core ordering domain logic.
- **Multi-Tenant Readiness**: Models and repositories include multi-restaurant isolation mixins (`restaurant_id`) so all restaurant-owned resources are cleanly partitioned.
- **Customer Privacy**: Customer WhatsApp identifiers remain quarantined in internal integration layers and are never exposed directly to kitchen operational dashboards.

---

## 📂 Project Structure

```text
whatsapp-restaurant-ordering/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   └── health.py       # GET /api/v1/health
│   │       └── router.py           # v1 router aggregator
│   ├── core/
│   │   ├── config.py               # Pydantic Settings
│   │   ├── exceptions.py           # Structured application exceptions
│   │   └── logging.py              # Centralized logging
│   ├── database/
│   │   ├── base.py                 # Declarative Base metadata
│   │   └── session.py              # Async SQLAlchemy engine & sessionmaker
│   ├── models/
│   │   └── base.py                 # DeclarativeBase, Timestamp & Restaurant mixins
│   ├── schemas/
│   │   ├── common.py               # Error models and response wrappers
│   │   └── health.py               # Health check response model
│   ├── repositories/
│   │   └── base.py                 # BaseRepository & BaseRestaurantRepository
│   ├── services/
│   │   └── base.py                 # BaseService
│   ├── integrations/               # Decoupled external integrations (e.g. WhatsApp)
│   └── main.py                     # FastAPI application factory & lifespan
├── migrations/                     # Alembic async migration environment
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── tests/
│   ├── api/
│   │   └── test_health.py          # Health check endpoint test
│   ├── unit/
│   │   ├── test_config.py          # Settings and DB URL test
│   │   └── test_exceptions.py      # Error handling test
│   └── conftest.py                 # Async test client fixture
├── scripts/
│   └── verify_db.py                # Standalone DB connectivity checker
├── .env.example                    # Environment template
├── .gitignore                      # Git exclusion rules
├── alembic.ini                     # Alembic configuration
├── Dockerfile                      # Production Dockerfile
├── docker-compose.yml              # Local PostgreSQL 16 & API stack
├── pytest.ini                      # Pytest asyncio configuration
├── requirements.txt                # Pinned dependencies
└── README.md
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.12+ (tested up to 3.14)
- Docker & Docker Compose (optional for local containerized PostgreSQL)

### 2. Environment Setup
Copy the example environment file:
```bash
cp .env.example .env
```

### 3. Local Virtual Environment Setup
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.\.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Running PostgreSQL with Docker Compose
```bash
docker compose up -d postgres
```

### 5. Database Connectivity Check
```bash
python scripts/verify_db.py
```

### 6. Running Migrations
```bash
alembic upgrade head
```

### 7. Starting the API
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 🧪 Testing

Run all unit and integration tests with `pytest`:
```bash
pytest
```

Verbose test output:
```bash
pytest -v
```

---

## 📡 API Endpoints

- **Health Check**:
  `GET /api/v1/health`
  ```json
  {
    "status": "ok"
  }
  ```
- **Interactive Swagger Documentation**:
  `http://localhost:8000/docs`
- **ReDoc Documentation**:
  `http://localhost:8000/redoc`
- **OpenAPI JSON Schema**:
  `http://localhost:8000/api/v1/openapi.json`

---

## 💬 Interactive CLI WhatsApp Simulator (`scripts/simulate_chat.py`)

A full interactive console simulator that runs locally in your terminal, enabling developers to test customer dining sessions and kitchen operations without requiring live Meta Cloud API accounts, webhook tunnels (ngrok), or frontend applications.

### 🌟 Key Architecture & Safety Features
- **Zero Logic Duplication**: Directly invokes real backend domain services (`SessionService`, `CustomerMenuService`, `CartService`, `OrderService`, `BillingService`, `OrderNotificationService`).
- **Live Outbound WhatsApp Notification Feed**: Whenever kitchen order status updates occur, real outbound messages dispatched to the mock WhatsApp client are rendered immediately in the terminal.
- **Zero External Overhead / Auto-Fallback**: Automatically uses PostgreSQL or seamlessly falls back to a self-seeded local SQLite database (`dev_simulator.db`) if PostgreSQL is not running.
- **Customer Privacy Protection**: Customer phone numbers are masked (`+9******77`), and internal tokens are never displayed.

### 🚀 Running the Simulator

```bash
# Standard run (connects to PostgreSQL or auto-falls back to local SQLite)
python scripts/simulate_chat.py

# Force local SQLite mode
python scripts/simulate_chat.py --sqlite

# Custom customer phone number
python scripts/simulate_chat.py --phone "+919876543200"

# View CLI options
python scripts/simulate_chat.py --help
```

### 📋 Command Reference

#### Customer Commands
| Command | Description | Example |
| :--- | :--- | :--- |
| `qr [table]` | Simulate scanning a table QR code | `qr 1` |
| `tables [table]` | Simulate direct WhatsApp table picker | `tables 2` |
| `menu` / `categories` | View menu food categories | `menu` |
| `category <number>` | List items and prices in category | `category 1` |
| `add <item> [qty]` | Add item to cart (by number or name) | `add 1 2` |
| `cart` | View current cart items and subtotal | `cart` |
| `qty <item> <qty>` | Update quantity of cart item | `qty 1 3` |
| `remove <item>` | Remove item from active cart | `remove 1` |
| `clear` | Remove all items from active cart | `clear` |
| `confirm` / `checkout` | Place order from active cart | `confirm` |
| `orders` / `status` | View all placed orders & current statuses | `orders` |
| `order <order_num>` | View line items and details for an order | `order ORD-6E0039` |
| `bill` | Request consolidated dining bill | `bill` |
| `session` | Inspect active table session information | `session` |

#### Kitchen Commands
| Command | Description | State Transition |
| :--- | :--- | :--- |
| `kitchen orders` | View active kitchen queue | — |
| `kitchen accept <order>` | Accept new customer order | `NEW` $\rightarrow$ `ACCEPTED` |
| `kitchen preparing <ord>`| Move order into preparation | `ACCEPTED` $\rightarrow$ `PREPARING` |
| `kitchen ready <order>` | Mark order ready for pickup | `PREPARING` $\rightarrow$ `READY` |
| `kitchen served <order>`| Mark order delivered to table | `READY` $\rightarrow$ `SERVED` |
| `kitchen cancel <order>`| Cancel order (allowed in early states) | `NEW`/`ACCEPTED` $\rightarrow$ `CANCELLED` |

#### Settlement & Utility
| Command | Description |
| :--- | :--- |
| `settle` | Settle bill, archive cart, close session, free table |
| `restaurants` | List all available active restaurants |
| `restaurant <number>` | Switch active restaurant |
| `reset` | Clear local terminal session context |
| `help` | Display interactive command help |
| `exit` / `quit` | Exit the simulator |

### 🎬 Example Walkthrough

```text
> qr 1
QR detected.
Restaurant: SpiceBox
Table: Table 1
Session created.

> category 1
Starters
1. Chicken 65 — ₹240.00
2. Paneer 65 — ₹200.00

> add 1 2
Chicken 65 added to cart.
Quantity: 2

> confirm
Order created successfully: ORD-6E0039 (Total: ₹480.00)

> kitchen accept 1
Kitchen status updated:
ACCEPTED
----------------------------------------
 OUTBOUND WHATSAPP
----------------------------------------
Order ORD-6E0039
Your order has been accepted by the restaurant.
We'll start preparing it shortly.
----------------------------------------

> kitchen served 1
Kitchen status updated:
SERVED

> bill
==================================================
 BILL
==================================================
Table: Table 1
Bill: BILL-15C1D5
Chicken 65 × 2    ₹480.00
Subtotal: ₹480.00
Tax: ₹0.00
Total: ₹480.00

> settle
Bill BILL-15C1D5 settled.
Session closed. Table 1 is now available.
```

---

## 📱 Meta WhatsApp Cloud API Integration (Step 11)

The platform supports both local development mock simulation and direct production integration with the official **Meta WhatsApp Cloud API** (Graph API).

### 1. Dual Operational Modes (`WHATSAPP_MODE`)

| Mode | Environment Variable | Network Calls | Use Case |
| :--- | :--- | :--- | :--- |
| **Mock** | `WHATSAPP_MODE=mock` | Zero external HTTP calls. In-memory buffer records all outbound messages. | Local testing, unit/integration test suites, CLI chat simulation. |
| **Meta** | `WHATSAPP_MODE=meta` | Authenticated async HTTP requests via Graph API (`httpx.AsyncClient`). | Live WhatsApp messaging with verified Meta Business Accounts. |

> [!NOTE]
> The legacy flag `WHATSAPP_USE_MOCK=True/False` is bidirectionally synchronized with `WHATSAPP_MODE`.

### 2. Supported Message Types

- **Text Messages**: Plain conversational text messages.
- **Interactive Button Replies**: Up to 3 action buttons per message with labels automatically constrained to 20 characters per Meta specification.
- **Interactive Lists**: Category browsing, dish selection, and table pickers with sections and up to 10 rows per list.

### 3. Webhook Configuration with Meta for Developers

Configure your webhook in the [Meta App Dashboard](https://developers.facebook.com/apps/):

- **Callback URL**: `https://your-domain.com/api/v1/integrations/whatsapp/webhook`
- **Verify Token**: Must match `WHATSAPP_VERIFY_TOKEN`.
- **Webhook Subscriptions**: Subscribe to the `messages` field under the WhatsApp Business Account.
- **Security**: The backend verifies incoming events using HMAC-SHA256 signatures (`X-Hub-Signature-256`) against `WHATSAPP_APP_SECRET`.
- **Deduplication**: Inbound message IDs (`wamid...`) are persistently recorded in `webhook_events` to prevent duplicate processing on Meta webhook retries.

### 4. Required Environment Variables for Meta Mode

```dotenv
WHATSAPP_MODE=meta
WHATSAPP_ACCESS_TOKEN=your_permanent_system_user_token
WHATSAPP_PHONE_NUMBER_ID=your_meta_phone_number_id
WHATSAPP_BUSINESS_ACCOUNT_ID=your_meta_waba_id
WHATSAPP_APP_SECRET=your_meta_app_secret
WHATSAPP_VERIFY_TOKEN=your_secure_verification_token
WHATSAPP_API_VERSION=v21.0
WHATSAPP_REQUEST_TIMEOUT=10.0
```

### 5. Security & Privacy Guarantees

- **Token Safety**: Meta access tokens, app secrets, and database credentials are never committed, logged, or returned in API responses.
- **PII Protection**: Customer phone numbers are masked in all logs and operational queues (e.g. `+9******77`).
- **Failure Isolation**: If Meta API returns an error or encounters a network timeout, the application logs a sanitized error, marks the notification as `FAILED`, and **never** rolls back committed kitchen orders or table sessions.


