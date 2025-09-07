from services.env_loader import load_env_multi
from services.logging_config import get_logger
from services.api_client import api_client
from ui.main_window import BudgetApp
import os

def main():
    """Main entry point for the budget application."""
    load_env_multi()
    logger = get_logger("budget")

    # Test API connection
    try:
        # Simple health check
        import requests
        api_url = os.getenv("API_BASE_URL", "https://fastapi-production-eadf.up.railway.app")
        response = requests.get(f"{api_url}/healthz", timeout=10)
        response.raise_for_status()
        logger.info("API connection successful: %s", api_url)
    except Exception as e:
        logger.warning("API connection failed: %s", e)
        logger.info("The app will still work, but data operations may fail")

    # Create and run main application (no more GitHub sync)
    app = BudgetApp(api_client=api_client, logger=logger)
    app.mainloop()

if __name__ == "__main__":
    main()
