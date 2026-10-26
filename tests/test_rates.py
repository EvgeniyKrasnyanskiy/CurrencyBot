"""
Unit tests for rates calculation, history persistence, and cold start recovery.
"""
import os
import json
import time
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

import currency_bot
from currency_bot import (
    load_rates_history,
    save_rates_history,
    get_all_rates
)

class TestRatesHistoryAndColdStart(unittest.TestCase):
    def test_load_save_rates_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "rates_history.json")
            with patch("currency_bot.os.path.exists") as mock_exists, \
                 patch("builtins.open", create=True) as mock_open:
                now = time.time()
                history_r = [(now - 100, 85.0), (now - 90000, 80.0)]
                history_c = [(now - 50, 84.5)]

                saved_data = {}
                def fake_dump(obj, f, **kwargs):
                    saved_data.update(obj)

                with patch("json.dump", side_effect=fake_dump):
                    save_rates_history(history_r, history_c)

                self.assertIn("history_r", saved_data)
                self.assertIn("history_c", saved_data)

                # Test load with cutoff filtering
                mock_exists.return_value = True
                with patch("json.load", return_value=saved_data):
                    loaded_r, loaded_c = load_rates_history()
                    # (now - 90000) is older than 86400, so it should be filtered out
                    self.assertEqual(len(loaded_r), 1)
                    self.assertEqual(loaded_r[0][1], 85.0)
                    self.assertEqual(len(loaded_c), 1)
                    self.assertEqual(loaded_c[0][1], 84.5)

    @patch("currency_bot.requests.get")
    def test_get_all_rates_cold_start(self, mock_get):
        now_dt = datetime.now()
        start_of_day_ms = int(datetime(now_dt.year, now_dt.month, now_dt.day).timestamp() * 1000)

        # Mock Rapira candles: [timestamp_ms, open, high, low, close, volume]
        rapira_candles = [
            [start_of_day_ms, 84.00, 84.50, 83.80, 84.10, 1000.0],
            [start_of_day_ms + 3600000, 84.10, 84.80, 84.00, 84.60, 2000.0]
        ]
        mock_rapira_resp = MagicMock()
        mock_rapira_resp.status_code = 200
        mock_rapira_resp.json.return_value = rapira_candles

        # Mock CoinGecko
        mock_cg_resp = MagicMock()
        mock_cg_resp.status_code = 200
        mock_cg_resp.json.return_value = {
            "tether": {
                "rub": 81.25,
                "rub_24h_change": 0.65
            }
        }

        def side_effect(url, **kwargs):
            if "rapira" in url:
                return mock_rapira_resp
            return mock_cg_resp

        mock_get.side_effect = side_effect

        history_r = []
        history_c = []
        msg, val_r, val_c = get_all_rates(history_r, history_c)

        self.assertEqual(val_r, 84.60)
        self.assertEqual(val_c, 81.25)
        # Verify second line is present right away on cold start
        self.assertIn("📈", msg)
        self.assertIn("(Rap)", msg)
        self.assertIn("(CG)", msg)
        self.assertIn("+0.71% (Rap)", msg)  # (84.60 - 84.00) / 84.00 * 100 = +0.71%
        self.assertIn("+0.65% (CG)", msg)

        # Verify history_r was seeded from Rapira candles
        self.assertTrue(len(history_r) >= 2)
        # Verify history_c has initial baseline
        self.assertTrue(len(history_c) >= 1)

    @patch("currency_bot.requests.get")
    def test_get_all_rates_warm_start(self, mock_get):
        now_dt = datetime.now()
        start_of_day = datetime(now_dt.year, now_dt.month, now_dt.day).timestamp()

        mock_rapira_resp = MagicMock()
        mock_rapira_resp.status_code = 200
        mock_rapira_resp.json.return_value = [
            [int(start_of_day * 1000), 80.0, 80.5, 79.9, 80.0, 500],
            [int((start_of_day + 100) * 1000), 80.0, 82.5, 80.0, 82.0, 500]
        ]

        mock_cg_resp = MagicMock()
        mock_cg_resp.status_code = 200
        mock_cg_resp.json.return_value = {
            "tether": {
                "rub": 80.00,
                "rub_24h_change": -0.50
            }
        }

        def side_effect(url, **kwargs):
            if "rapira" in url:
                return mock_rapira_resp
            return mock_cg_resp

        mock_get.side_effect = side_effect

        # History with midnight points
        history_r = [(start_of_day + 10, 80.0), (start_of_day + 100, 81.0)]
        history_c = [(start_of_day + 10, 80.5), (start_of_day + 100, 80.2)]

        msg, val_r, val_c = get_all_rates(history_r, history_c)
        self.assertIn("📈", msg)
        self.assertIn("+2.50% (Rap)", msg)  # (82.0 - 80.0) / 80.0 * 100 = +2.50%
        self.assertIn("-0.62% (CG)", msg)   # (80.0 - 80.5) / 80.5 * 100 = -0.62%

if __name__ == '__main__':
    unittest.main()
