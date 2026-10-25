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
