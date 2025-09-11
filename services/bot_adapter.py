"""
Adapter layer for Telegram bot to replace bd.py functions with async API calls.
This allows minimal changes to existing bot code.
"""
from services.api_client import AsyncBudgetApiClient
from typing import List, Tuple, Dict, Optional
import asyncio
import logging

# Set up logging
logger = logging.getLogger("budget-bot-adapter")
logger.setLevel(logging.INFO)

# Global async API client instance
_async_api_client = None

def get_async_api_client() -> AsyncBudgetApiClient:
    """Get or create global async API client instance."""
    global _async_api_client
    if _async_api_client is None:
        _async_api_client = AsyncBudgetApiClient()
    return _async_api_client

# --- Async functions that replace bd.py functions for bot ---

async def add_expense(category: str, amount: float) -> Tuple[bool, float]:
    """Add expense. Returns (exceeded_limit, remaining_amount)"""
    try:
        logger.info(f"Bot adapter: Adding expense {category}=${amount}")
        result = await get_async_api_client().add_expense(category, amount)
        logger.info(f"Bot adapter: Add expense result: {result}")
        return result
    except Exception as e:
        logger.error(f"Bot adapter: Failed to add expense {category}=${amount}: {e}")
        # Return default values to prevent bot crash
        return False, 0.0

async def get_month_report(month: str) -> Dict[str, Dict[str, float]]:
    """Get spending report for a month."""
    try:
        logger.info(f"Bot adapter: Getting month report for {month}")
        # Get raw API data
        api_data = await get_async_api_client().get_month_report(month)
        logger.info(f"Bot adapter: API returned report data: {api_data}")
        
        # FastAPI returns: {"report": {"category": {"spent": X, "budget": Y, "remaining": Z}}}
        report_data = api_data.get('report', {})
        
        # Convert to the format expected by bot: {category: {'spent': X, 'budget': Y}}
        result = {}
        for category, data in report_data.items():
            result[category] = {
                'spent': data.get('spent', 0.0),
                'budget': data.get('budget', 0.0)
            }
        
        logger.info(f"Bot adapter: Converted report: {result}")
        return result
    except Exception as e:
        logger.error(f"Bot adapter: Failed to get month report for {month}: {e}")
        # Return empty dict on error to avoid bot crashes
        return {}

async def get_remaining(category: str, month: str) -> float:
    """Get remaining budget for a specific category in a month."""
    try:
        # Get full report data
        api_data = await get_async_api_client().get_month_report(month)
        report_data = api_data.get('report', {})
        category_data = report_data.get(category, {})
        return category_data.get('remaining', 0.0)
    except Exception:
        return 0.0

async def list_limits() -> List[Tuple[str, float]]:
    """Get all category limits. Returns list of tuples: (category, limit)"""
    limits_list = await get_async_api_client().list_limits()
    return [(limit['category'], limit['default_limit']) for limit in limits_list]

async def set_limit(category: str, amount: float) -> None:
    """Set category limit."""
    await get_async_api_client().set_limit(category, amount)

def get_current_month() -> str:
    """Get current month in YYYY-MM format."""
    return get_async_api_client().get_current_month()

# --- Helper functions for bot ---

async def get_expenses_for_month(month: str) -> List[Dict]:
    """Get expenses for a specific month."""
    return await get_async_api_client().get_expenses_for_month(month)

# --- Notification functions ---

async def add_peer_if_new(user_id: int, username: str) -> None:
    """Add user to peers table if not already present."""
    try:
        logger.info(f"Bot adapter: Adding peer {user_id} ({username})")
        await get_async_api_client().add_peer(user_id, username)
        logger.info(f"Bot adapter: Peer added successfully")
    except Exception as e:
        logger.error(f"Bot adapter: Failed to add peer {user_id}: {e}")

async def get_peer_ids(exclude_id: Optional[int] = None, allowed_ids: Optional[List[int]] = None) -> List[int]:
    """Get list of peer IDs for notifications."""
    try:
        logger.info(f"Bot adapter: Getting peer IDs (exclude={exclude_id}, allowed={allowed_ids})")
        result = await get_async_api_client().get_peers(exclude_id=exclude_id)
        peer_ids = result.get('peer_ids', [])
        
        # Filter by allowed_ids if provided
        if allowed_ids and len(allowed_ids) > 0:
            peer_ids = [pid for pid in peer_ids if pid in allowed_ids]
        
        logger.info(f"Bot adapter: Found {len(peer_ids)} peers: {peer_ids}")
        return peer_ids
    except Exception as e:
        logger.error(f"Bot adapter: Failed to get peer IDs: {e}")
        return []

async def was_notified(category: str, month: str, threshold: int) -> bool:
    """Check if threshold notification was already sent."""
    try:
        logger.info(f"Bot adapter: Checking alert for {category} {month} {threshold}%")
        result = await get_async_api_client().check_alert(category, month, threshold)
        was_notified = result.get('was_notified', False)
        logger.info(f"Bot adapter: Alert check result: {was_notified}")
        return was_notified
    except Exception as e:
        logger.error(f"Bot adapter: Failed to check alert: {e}")
        return False

async def mark_notified(category: str, month: str, threshold: int) -> None:
    """Mark threshold notification as sent."""
    try:
        logger.info(f"Bot adapter: Marking alert as sent for {category} {month} {threshold}%")
        await get_async_api_client().mark_alert(category, month, threshold)
        logger.info(f"Bot adapter: Alert marked as sent")
    except Exception as e:
        logger.error(f"Bot adapter: Failed to mark alert: {e}")

async def maybe_notify_thresholds(category: str, month: str, context) -> None:
    """Send threshold notifications if needed (50% and 90%)."""
    try:
        # Get current month report to check thresholds
        report_data = await get_month_report(month)
        category_data = report_data.get(category, {})
        budget = float(category_data.get('budget', 0.0))
        spent = float(category_data.get('spent', 0.0))
        
        if budget <= 0:
            return  # No budget set, no notifications
        
        ratio = spent / budget
        thresholds = [50, 90]
        
        for threshold in thresholds:
            if ratio >= threshold / 100:
                # Check if already notified
                if not await was_notified(category, month, threshold):
                    # Send notification
                    if threshold == 50:
                        msg = f"⚠️ {category}: spend ⩾50% of limit! Spent ${spent:.2f} / ${budget:.2f}."
                    else:
                        msg = f"🔴 {category}: spend ⩾90% of limit!!! Spent ${spent:.2f} / ${budget:.2f}."
                    
                    # Send to current user
                    try:
                        from telegram import Update
                        if hasattr(context, 'bot') and hasattr(context, 'effective_chat'):
                            await context.bot.send_message(chat_id=context.effective_chat.id, text=msg)
                    except Exception as e:
                        logger.warning(f"Bot adapter: Failed to send threshold notification: {e}")
                    
                    # Mark as notified
                    await mark_notified(category, month, threshold)
                    
    except Exception as e:
        logger.error(f"Bot adapter: Failed to check thresholds for {category}: {e}")

async def notify_peers(sender_name: str, category: str, amount: float, currency_symbol: str, 
                      context, sender_id: Optional[int] = None, allowed_ids: Optional[List[int]] = None) -> None:
    """Send notification to other peers about expense addition."""
    try:
        logger.info(f"Bot adapter: Notifying peers about {sender_name} adding {category} ${amount}")
        
        # Add sender to peers
        if sender_id:
            await add_peer_if_new(sender_id, sender_name)
        
        # Get peer IDs
        peer_ids = await get_peer_ids(exclude_id=sender_id, allowed_ids=allowed_ids)
        
        if not peer_ids:
            logger.info("Bot adapter: No peers to notify")
            return
        
        # Send notifications
        notify_msg = f"{sender_name} added {category} {currency_symbol}{amount:.2f}"
        for peer_id in peer_ids:
            try:
                if hasattr(context, 'bot'):
                    await context.bot.send_message(chat_id=peer_id, text=notify_msg)
                    logger.info(f"Bot adapter: Notification sent to peer {peer_id}")
            except Exception as e:
                logger.warning(f"Bot adapter: Failed to send notification to peer {peer_id}: {e}")
                
    except Exception as e:
        logger.error(f"Bot adapter: Failed to notify peers: {e}")
