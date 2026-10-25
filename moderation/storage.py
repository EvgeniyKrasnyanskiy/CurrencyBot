"""
Storage and state management for Exchange topic moderation.
Tracks active user ads, limits, and welcome message status.
"""
import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join("data", "moderation_state.json")

class ModerationStorage:
    def __init__(self, state_file: str = STATE_FILE):
        self.state_file = state_file
        self.state: Dict[str, Any] = {
            "welcome_sent": False,
            "welcome_message_id": None,
            "user_ads": {},  # {user_id_str: {"message_id": int, "timestamp": float, "text": str}}
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

    # --- Ads Tracking ---
    def register_ad(self, user_id: int, message_id: int, timestamp: float, text: str):
        """Register a valid exchange ad."""
        uid_str = str(user_id)
        self.state["user_ads"][uid_str] = {
            "message_id": message_id,
            "timestamp": timestamp,
            "text": text[:200]
        }
        if message_id not in self.state["known_ad_message_ids"]:
            self.state["known_ad_message_ids"].append(message_id)
            # Keep only last 1000 ad IDs in memory
            if len(self.state["known_ad_message_ids"]) > 1000:
                self.state["known_ad_message_ids"] = self.state["known_ad_message_ids"][-1000:]
        self.save()

    def update_ad_text(self, user_id: int, message_id: int, new_text: str):
        """Update existing ad upon edit."""
        uid_str = str(user_id)
        if uid_str in self.state["user_ads"] and self.state["user_ads"][uid_str]["message_id"] == message_id:
            self.state["user_ads"][uid_str]["text"] = new_text[:200]
            self.save()

    def get_user_ad(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get active ad for user if any."""
        return self.state["user_ads"].get(str(user_id))

    def is_known_ad_message(self, message_id: int) -> bool:
        """Check if message_id belongs to a recognized ad."""
        return message_id in self.state["known_ad_message_ids"]
