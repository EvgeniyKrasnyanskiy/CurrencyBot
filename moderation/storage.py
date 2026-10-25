"""
Storage and state management for Exchange topic moderation.
Tracks user ads history (up to N ads per 24h) and welcome message status.
"""
import os
import json
import time
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join("data", "moderation_state.json")

class ModerationStorage:
    def __init__(self, state_file: str = STATE_FILE):
        self.state_file = state_file
        self.state: Dict[str, Any] = {
            "welcome_sent": False,
            "welcome_message_id": None,
            "user_ads": {},  # {user_id_str: [{"message_id": int, "timestamp": float, "text": str}]}
            "known_ad_message_ids": [] # list of message_ids of valid ads
        }
        self.load()

    def load(self):
        """Load moderation state from JSON file."""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.state.update(data)
                # Ensure user_ads entries are lists
                for uid, ads in list(self.state.get("user_ads", {}).items()):
                    if isinstance(ads, dict):
                        self.state["user_ads"][uid] = [ads]
        except Exception as e:
            logger.error(f"Error loading moderation state: {e}")

    def save(self):
        """Persist state to JSON file."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving moderation state: {e}")

    # --- Welcome Message ---
    def is_welcome_sent(self) -> bool:
        return bool(self.state.get("welcome_sent", False))

    def mark_welcome_sent(self, message_id: int):
        self.state["welcome_sent"] = True
        self.state["welcome_message_id"] = message_id
        self.save()

    # --- Ads Tracking (per 24 hours) ---
    def get_user_recent_ads(self, user_id: int, window_seconds: int = 86400) -> List[Dict[str, Any]]:
        """Get ads posted by user in the last window_seconds (default 24h)."""
        uid_str = str(user_id)
        ads = self.state["user_ads"].get(uid_str, [])
        now = time.time()
        # Filter active ads within window
        valid_ads = [ad for ad in ads if now - ad.get("timestamp", 0) < window_seconds]
        if len(valid_ads) != len(ads):
            self.state["user_ads"][uid_str] = valid_ads
            self.save()
        return valid_ads

    def register_ad(self, user_id: int, message_id: int, timestamp: float, text: str):
        """Register a valid exchange ad for user."""
        uid_str = str(user_id)
        if uid_str not in self.state["user_ads"]:
            self.state["user_ads"][uid_str] = []

        new_entry = {
            "message_id": message_id,
            "timestamp": timestamp,
            "text": text[:200]
        }
        self.state["user_ads"][uid_str].append(new_entry)

        if message_id not in self.state["known_ad_message_ids"]:
            self.state["known_ad_message_ids"].append(message_id)
            if len(self.state["known_ad_message_ids"]) > 1000:
                self.state["known_ad_message_ids"] = self.state["known_ad_message_ids"][-1000:]
        self.save()

    def update_ad_text(self, user_id: int, message_id: int, new_text: str):
        """Update existing ad text upon user edit."""
        uid_str = str(user_id)
        ads = self.state["user_ads"].get(uid_str, [])
        updated = False
        for ad in ads:
            if ad.get("message_id") == message_id:
                ad["text"] = new_text[:200]
                updated = True
                break
        if updated:
            self.save()
