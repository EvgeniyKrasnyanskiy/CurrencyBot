"""
Moderation configuration loader and dataclass.
"""
import os
import json
from typing import List, Optional

class ModerationConfig:
    def __init__(self):
        # Master toggle
        self.enabled: bool = os.getenv("MODERATION_ENABLED", "True").lower() in ("true", "1", "yes")
        
        # Target destination
        self.target_group_id: Optional[int] = (
            int(os.getenv("MODERATION_TARGET_GROUP_ID")) if os.getenv("MODERATION_TARGET_GROUP_ID")
            else (int(os.getenv("CHANNEL_ID")) if os.getenv("CHANNEL_ID") else None)
        )
        self.target_thread_id: Optional[int] = (
            int(os.getenv("MODERATION_TARGET_THREAD_ID")) if os.getenv("MODERATION_TARGET_THREAD_ID")
            else (int(os.getenv("TOPIC_ID")) if os.getenv("TOPIC_ID") else None)
        )

        # Warning & deletion delay (seconds)
        self.warning_delete_delay: int = int(os.getenv("WARNING_DELETE_DELAY", "60"))

        # Welcome message setting
        self.welcome_message_enabled: bool = os.getenv("WELCOME_MESSAGE_ENABLED", "True").lower() in ("true", "1", "yes")

        # Allow textual replies to other users' ads
        self.allow_replies_to_ads: bool = os.getenv("ALLOW_REPLIES_TO_ADS", "True").lower() in ("true", "1", "yes")

        # Rate limits
        self.max_active_ads_per_user: int = int(os.getenv("MAX_ACTIVE_ADS_PER_USER", "1"))

        # Whitelist / Admins bypass
        env_whitelist = os.getenv("MODERATION_WHITELIST_USERS", "[]")
        try:
            self.whitelist_users: List[int] = json.loads(env_whitelist)
        except Exception:
            self.whitelist_users = []

        # Merge with global ADMINS if present
        env_admins = os.getenv("ADMINS", "[]")
        try:
            admin_ids = json.loads(env_admins)
            for a_id in admin_ids:
                if a_id not in self.whitelist_users:
                    self.whitelist_users.append(a_id)
        except Exception:
            pass

    def is_user_exempt(self, user_id: int) -> bool:
        """Check if user can bypass moderation."""
        return user_id in self.whitelist_users
