# Budget Pet - Family Budget Manager

A comprehensive family budget management application with desktop GUI, Telegram bot, and REST API.

## Features

### Desktop GUI
- **Expense Management**: Add, edit, delete expenses with category filtering
- **Budget Tracking**: Set monthly limits per category with rollover support
- **Visual Analytics**: Pie/bar charts and spending trends
- **Advanced Search**: Filter by amount ranges, dates, categories
- **Comparison**: Compare spending between months
- **GitHub Sync**: Automatic synchronization of database via GitHub

### Telegram Bot
- **Quick Expense Entry**: Add expenses via text commands
- **Real-time Notifications**: Budget threshold alerts (50%, 90%)
- **Reports**: Monthly summaries and category breakdowns
- **Multi-user Support**: Shared budget with user management

### REST API
- **Full CRUD**: Complete expense and budget management
- **Advanced Filtering**: Same search capabilities as GUI
- **Reports**: Monthly reports with comparisons
- **GitHub Integration**: Automatic sync with desktop/bot

## Architecture

```
budget_pet/
├── app.py              # Desktop GUI entry point
├── web/main.py         # FastAPI web service
├── ui/                 # GUI components
├── services/           # Business logic services
├── domain/             # Domain models/helpers
├── bd.py               # Database operations
└── github_sync.py      # GitHub synchronization
```

## Installation

### Prerequisites
- Python 3.11+
- SQLite (built-in)
- GitHub account (for sync)

### Setup
1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd budget_pet
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables (create `.env` file):
   ```bash
   # GitHub sync (required for multi-device sync)
   GITHUB_TOKEN=your_github_token
   GITHUB_OWNER=your_github_username
   GITHUB_REPO=budget_pet
   GITHUB_DB_PATH=budget.db
   GITHUB_BRANCH=main

   # Telegram bot (optional)
   TG_BOT_TOKEN=your_bot_token
   TG_ALLOWED_USER_IDS=123456789,987654321

   # Web API admin key (optional)
   ADMIN_KEY=your_admin_key
   ```

## Usage

### Desktop Application
```bash
# Run the GUI application
python -m budget_pet.app
```

### Web API
```bash
# Run the web service locally
uvicorn web.main:app --host 0.0.0.0 --port 8000

# Or use the PORT environment variable
PORT=8000 uvicorn web.main:app --host 0.0.0.0 --port $PORT
```

### Telegram Bot
```bash
# Run the Telegram bot
python bot.py
```

## API Documentation

### Endpoints

#### Health Check
- `GET /healthz` - Service health check

#### Expenses
- `GET /expenses?month=2024-01&query=food` - Get expenses with filtering
- `POST /expenses` - Create new expense
- `PATCH /expenses/{id}` - Update expense
- `DELETE /expenses/{id}` - Delete expense

#### Reports
- `GET /report?month=2024-01&compare=2023-12` - Monthly report with comparison

#### Limits
- `GET /limits` - Get all category limits
- `POST /limits` - Create/update category limit

#### Categories
- `DELETE /categories/{name}` - Delete category and all expenses

#### Synchronization
- `GET /sync/status` - Get sync status
- `POST /sync/pull` - Pull latest from GitHub (admin only)
- `POST /sync/push` - Push to GitHub (admin only)

### Search Query Syntax
- **Category substring**: `food` - expenses containing "food"
- **Amount range**: `100..500` - amounts between 100 and 500
- **Amount operators**: `>100`, `<=200`, `=50`
- **Date range**: `2024-01-01..2024-01-31`
- **Date prefix**: `2024-01` - all of January 2024

## Deployment

### Railway (Recommended)
1. Create a new Web service in Railway
2. Connect your GitHub repository
3. Set environment variables in Railway dashboard:
   - `PORT` (auto-assigned)
   - `GITHUB_TOKEN`
   - `GITHUB_OWNER`
   - `GITHUB_REPO`
   - `GITHUB_DB_PATH`
   - `GITHUB_BRANCH`
   - `ADMIN_KEY` (optional)
4. Railway will automatically build and deploy using the provided Dockerfile

### Local Docker
```bash
# Build the image
docker build -t budget-pet .

# Run locally
docker run -p 8000:8000 -e PORT=8000 budget-pet
```

## Development

### Project Structure
- `ui/` - Desktop GUI components
- `services/` - Business logic and external services
- `web/` - REST API implementation
- `domain/` - Domain models and helpers
- `bd.py` - Database operations
- `github_sync.py` - GitHub synchronization

### Adding New Features
1. **GUI Features**: Add to appropriate `ui/` module
2. **API Endpoints**: Add to `web/main.py` with Pydantic models in `web/schemas.py`
3. **Business Logic**: Add to `services/` modules
4. **Database**: Extend `bd.py` functions

### Testing
```bash
# Test GUI functionality
python -m budget_pet.app

# Test API endpoints
curl http://localhost:8000/healthz

# Test with different search queries
curl "http://localhost:8000/expenses?month=2024-01&query=food"
```

## Configuration

### Environment Variables
- `GITHUB_TOKEN` - GitHub personal access token
- `GITHUB_OWNER` - GitHub repository owner
- `GITHUB_REPO` - Repository name
- `GITHUB_DB_PATH` - Path to database file in repo (default: budget.db)
- `GITHUB_BRANCH` - Branch to sync with (default: main)
- `TG_BOT_TOKEN` - Telegram bot token
- `TG_ALLOWED_USER_IDS` - Comma-separated list of allowed Telegram user IDs
- `ADMIN_KEY` - Admin key for sensitive API endpoints
- `PORT` - Port for web service (Railway sets this automatically)

### Database
The application uses SQLite with the following tables:
- `expenses` - Expense records
- `category_limits` - Category budget limits
- `monthly_budgets` - Monthly budget tracking with rollover
- `settings` - Application settings
- `peers` - Telegram bot users
- `budget_alerts` - Notification tracking

## Contributing

1. Create a feature branch
2. Make your changes
3. Test both GUI and API functionality
4. Ensure all existing features work
5. Submit a pull request

## License

[Your License Here]
