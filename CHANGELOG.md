# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-10-26

### Added
- **Exchange Topic Moderation**:
  - Automatic moderation specifically for the target exchange topic (`TARGET_GROUP_ID` & `TARGET_THREAD_ID`).
  - Text classification (`EXCHANGE`, `EXCHANGE_REPLY`, `SPAM`, `CHAT`, `UNKNOWN`).
  - Allowed textual replies between participants on exchange ads (`ALLOW_REPLIES_TO_ADS`).
  - Forbidden media filtering (stickers, GIFs, voice, video notes, photos, videos, files).
  - Warning reply on violation with reason and explanation.
  - Delayed automatic deletion of both violating message and warning reply (default: 60s).
  - One-time welcome announcement with topic rules (`WELCOME_MESSAGE_ENABLED`).
  - State tracking in `data/moderation_state.json` (active ads per user, welcome announcement flag).
  - Dedicated moderation log in `logs/moderation.log`.
  - Comprehensive unit test suite in `tests/test_moderation.py`.
