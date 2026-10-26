# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-10-26

### Added
- **Exchange Topic Moderation**:
  - Automatic moderation specifically for the target exchange topic (`TARGET_GROUP_ID` & `TARGET_THREAD_ID`).
  - Strict text classification (`EXCHANGE`, `SPAM`, `CHAT`).
  - All non-exchange messages and replies are prohibited from the topic, redirecting users to DM or main chat.
  - Limit of **2 active ads per user in 24 hours** (`MAX_ACTIVE_ADS_PER_USER=2`).
  - **Live Log Channel**: Option to stream all moderation events directly into a private Telegram channel (`MODERATION_LOG_CHANNEL_ID`).
  - Forbidden media filtering (stickers, GIFs, voice, video notes, photos, videos, files).
  - Warning reply on violation with reason and explanation.
  - Delayed automatic deletion of both violating message and warning reply (default: 60s).
  - One-time welcome announcement with topic rules (`WELCOME_MESSAGE_ENABLED`).
  - State tracking in `data/moderation_state.json`.
  - Comprehensive unit test suite in `tests/test_moderation.py`.

### Fixed
- **Moderation False Positives**:
  - Excluded forum topic creation service messages (`forum_topic_created` / `message_thread_id`), replies to the bot (pinned rates / welcome rules), and user self-replies from being treated as forbidden participant replies.
  - Allowed valid standalone exchange announcements (e.g. "Продам 180 usdt по 82 на карту") even if a reply reference is present, while strictly filtering direct discussions and negotiations directed at other users.
- **Rate Message Pinning**:
  - Implemented case-insensitive error detection for missing/deleted Telegram messages (`message to edit not found`).
  - Added immediate re-creation and pinning of the rate message upon detecting deletion, eliminating the 10-minute delay.
  - Added lookup for existing pinned bot message on startup to prevent duplicates.
- **Log Rotation**:
  - Configured `RotatingFileHandler` for `logs/currency_bot.log` and `logs/moderation.log` (5 MB max per file, 3 backup archives) to prevent unlimited disk growth.
