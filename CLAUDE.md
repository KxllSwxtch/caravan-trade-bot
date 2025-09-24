# CaravanTrade Telegram Bot - Claude Development Guide

You're an expert in Telegram bot development with 20+ years of experience. You know everything about Python language, web scraping, database design, API integrations, and building robust production-ready bots. This project is a sophisticated car import calculator and order management system for Korean car markets.

## Project Overview

**CaravanTrade Bot** is a Telegram bot that helps users calculate car import costs from Korea to Russia. The bot scrapes car data from Korean websites (Encar.com, KBChaCha.com, KCar.com), calculates customs fees, and manages customer orders through a complete workflow system.

### Core Business Logic

- **Car Cost Calculation**: Scrapes Korean car sites, calculates total import costs including customs fees
- **Order Management**: Full order lifecycle from creation to delivery tracking
- **Subscription System**: Premium features with channel subscription verification
- **Manager Dashboard**: Order status management for administrators
- **Currency Exchange**: Real-time KRW/RUB/USD exchange rates

## Tech Stack & Architecture

### Core Technologies

- **Python 3.13** - Main language
- **pyTelegramBotAPI 4.25.0** - Telegram Bot API wrapper
- **PostgreSQL** - Primary database (Heroku Postgres)
- **BeautifulSoup4** - Web scraping
- **Selenium + Playwright** - Dynamic content scraping
- **APScheduler** - Background tasks and rate limiting
- **psycopg2** - PostgreSQL adapter

### Project Structure

```
caravan-trade-bot/
├── main.py              # Main bot logic (2500+ lines)
├── database.py          # PostgreSQL database operations
├── utils.py             # Car calculation utilities
├── rate_limiter.py      # API rate limiting system
├── get_currency_rates.py # Currency exchange rates
├── test.py              # Testing utilities
├── requirements.txt     # Dependencies
├── Procfile            # Heroku deployment
├── runtime.txt         # Python version
└── bot.log             # Application logs
```

## Database Schema

### Tables Structure

```sql
-- Orders table - Main order tracking
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    car_id TEXT NOT NULL,
    title TEXT NOT NULL,
    price TEXT,
    link TEXT NOT NULL,
    year TEXT,
    month TEXT,
    mileage TEXT,
    engine_volume INT,
    transmission TEXT,
    user_name TEXT,
    full_name TEXT,
    phone_number TEXT,
    images TEXT[],
    status TEXT DEFAULT '🔄 Не заказано',
    total_cost_usd FLOAT,
    total_cost_krw FLOAT,
    total_cost_rub FLOAT
);

-- Users table - User management
CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    timestamp TIMESTAMP
);

-- Calculations table - Usage tracking
CREATE TABLE calculations (
    user_id BIGINT PRIMARY KEY,
    count INT DEFAULT 0
);

-- Subscriptions table - Premium features
CREATE TABLE subscriptions (
    user_id BIGINT PRIMARY KEY,
    status BOOLEAN DEFAULT FALSE
);
```

### Key Database Functions

- `add_order(order)` - Create new order: database.py:80
- `get_orders(user_id)` - Get user orders: database.py:114
- `update_order_status_in_db(order_id, status)` - Update status: database.py:200+
- `get_all_orders()` - Admin order view: database.py:160+

## Bot Commands & Handlers

### Core Commands Structure (main.py)

- `/start` - Welcome message and setup: main.py:1061
- `/my_cars` - User's saved cars: main.py:176
- `/orders` - Order management: main.py:545
- `/stats` - Admin statistics: main.py:832
- `/exchange_rates` - Currency rates: main.py:1020

### Callback Handlers

- `add_favorite_*` - Save car to favorites: main.py:118
- `order_car_*` - Place new order: main.py:286
- `update_status_*` - Manager status updates: main.py:613
- `place_order_*` - Confirm order placement: main.py:738
- `check_subscription` - Verify channel subscription: main.py:775

### Main Message Handler

- Car URL processing and calculation: main.py:2496
- FAQ system: main.py:1947-2020
- Contact information handling: main.py:360-420

## Car Calculation System

### Supported Websites

1. **Encar.com** - Primary Korean car marketplace
2. **KBChaCha.com** - Secondary marketplace
3. **KCar.com** - Alternative source

### Calculation Process (main.py:1321)

```python
def calculate_cost(link, message):
    # 1. Parse car URL and extract data
    # 2. Scrape car information (price, specs, images)
    # 3. Calculate customs fees via calcus.ru API
    # 4. Apply additional costs (delivery, insurance, etc.)
    # 5. Convert currencies (KRW → RUB, USD)
    # 6. Display comprehensive cost breakdown
```

### Cost Components

- **Car Price** - Base price from Korean site
- **Customs Duties** - Via calcus.ru API integration: utils.py:49-134
- **Delivery** - Fixed rate based on car price
- **Insurance** - Calculated percentage: main.py:1780
- **Technical Card** - Administrative fees: main.py:1815
- **Total Cost** - All-inclusive price in KRW/RUB/USD

## API Integrations & Rate Limiting

### External APIs

1. **calcus.ru** - Russian customs calculator

   - Rate limited: 5 requests/second
   - Retry logic with exponential backoff
   - Implementation: utils.py:49-134, rate_limiter.py:65-149

2. **Currency APIs** - Exchange rates
   - Multiple sources for reliability
   - KRW/RUB, USD/RUB, USDT/KRW rates
   - Implementation: main.py:878-1019

### Rate Limiting System (rate_limiter.py)

```python
# Thread-safe rate limiter with retry logic
calcus_rate_limiter = RetryableRateLimiter(
    max_requests=5,     # 5 requests per second
    time_window=1.0,    # 1 second window
    max_retries=4,      # 4 retry attempts
    base_delay=1.0      # Exponential backoff starting at 1s
)
```

## Order Management System

### Order Statuses (main.py:99-108)

```python
ORDER_STATUSES = {
    "1": "🚗 Авто выкуплен (на базе)",
    "2": "🚢 Авто в пути в Россию",
    "3": "🏭 Авто на складе в России",
    "4": "📋 Авто проходит таможенное оформление",
    "5": "🎯 Авто готов к выдаче",
    "6": "✅ Авто выдан клиенту",
    "7": "❌ Заказ отменён"
}
```

### Manager System

- Authorized managers: main.py:92-97
- Order status updates with notifications
- Complete order tracking workflow

## Subscription & Access Control

### Channel Verification

- Required subscription to @crvntrade
- Automatic verification via Telegram API
- Premium calculation features locked behind subscription
- Implementation: main.py:775-831

### Usage Limits

- Free users: Limited calculations per day
- Subscribers: Unlimited access
- Database tracking of calculation counts

## Development Guidelines

### Code Style & Patterns

- **Single File Architecture**: Main logic in main.py (manageable for bot complexity)
- **Global Variables**: Used for currency rates and temporary data storage
- **Error Handling**: Try-catch blocks around external API calls
- **Logging**: Comprehensive logging to bot.log
- **Threading**: ThreadPoolExecutor for concurrent operations

### Common Patterns

```python
# Standard callback handler pattern
@bot.callback_query_handler(func=lambda call: call.data.startswith("prefix_"))
def handler_name(call):
    # Extract data from callback
    # Perform business logic
    # Update database
    # Send user response
    # Handle errors gracefully

# Database operation pattern
def db_operation():
    with connect_db() as conn:
        with conn.cursor() as cur:
            # Execute SQL
            conn.commit()
```

### Error Handling Strategy

- Rate limiting for external APIs
- Graceful degradation for scraping failures
- User-friendly error messages
- Manager notifications for critical errors

## Testing & Debugging

### Test File (test.py)

- Manual testing functions
- Database connection tests
- API integration tests
- Sample data generation

### Debugging Approaches

- Bot log monitoring: `tail -f bot.log`
- Database queries for order tracking
- Manual rate limit testing
- Currency rate validation

## Deployment & Configuration

### Environment Variables

```bash
BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql://...
```

### Heroku Configuration

- **Procfile**: `worker: python main.py`
- **Runtime**: Python 3.13
- **Add-ons**: Heroku Postgres
- **Buildpacks**: Python + custom for dependencies

### Production Considerations

- **Proxies**: Configured for Korean sites access
- **User Agents**: Rotation to avoid blocking
- **Rate Limiting**: Prevents API abuse
- **Database Connections**: Proper connection pooling
- **Logging**: Structured logging for monitoring

## Key Implementation Notes

### Car Data Extraction

- Dynamic content requires Selenium/Playwright
- Image URL generation: utils.py:141-151
- Price cleaning and formatting: utils.py:136-139
- Age calculation for customs: utils.py:21-47

### Currency Handling

- Multiple exchange rate sources for reliability
- Real-time rate updates with caching
- Proper number formatting for Russian locale
- Error handling for rate API failures

### Bot State Management

- Global variables for temporary data
- Database persistence for permanent data
- User session handling through Telegram user IDs
- Manager privileges through hardcoded user IDs

This bot represents a sophisticated business application with real-world complexity including payment processing, international shipping calculations, and customer service workflows. The codebase demonstrates advanced Python patterns, external API integration, and production-ready error handling.
