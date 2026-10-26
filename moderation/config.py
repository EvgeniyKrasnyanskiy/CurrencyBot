"""
Moderation configuration loader and dataclass.
"""
import os
import json
from typing import List, Optional
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()


def _parse_int(val: Optional[str]) -> Optional[int]:
    """Safely parse integer from env, handling empty strings and whitespace."""
    if val is None:
        return None
    val = str(val).strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


class ModerationConfig:
    def __init__(self):
        # Master toggle
        self.enabled: bool = os.getenv("MODERATION_ENABLED", "True").lower() in ("true", "1", "yes")
        
        # Target destination
        self.target_group_id: Optional[int] = (
            _parse_int(os.getenv("MODERATION_TARGET_GROUP_ID")) or _parse_int(os.getenv("CHANNEL_ID"))
        )
        self.target_thread_id: Optional[int] = (
            _parse_int(os.getenv("MODERATION_TARGET_THREAD_ID")) or _parse_int(os.getenv("TOPIC_ID"))
        )

        # Telegram Log Channel for moderation events (e.g. -100...)
        self.log_channel_id: Optional[int] = _parse_int(os.getenv("MODERATION_LOG_CHANNEL_ID"))

        # Warning & deletion delay (seconds)
        self.warning_delete_delay: int = _parse_int(os.getenv("WARNING_DELETE_DELAY")) or 60

        # Welcome message setting
        self.welcome_message_enabled: bool = os.getenv("WELCOME_MESSAGE_ENABLED", "True").lower() in ("true", "1", "yes")

        # Allow textual replies to other users' ads (Default: False for clean board)
        self.allow_replies_to_ads: bool = os.getenv("ALLOW_REPLIES_TO_ADS", "False").lower() in ("true", "1", "yes")

        # Rate limits (Default: 2 ads per 24 hours)
        self.max_active_ads_per_user: int = _parse_int(os.getenv("MAX_ACTIVE_ADS_PER_USER")) or 2

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
