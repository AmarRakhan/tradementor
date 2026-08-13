import unittest

from close_all import execute_close_all


class CloseAllTest(unittest.TestCase):
    def test_every_unique_open_position_is_closed_once(self):
        positions = [{"coin": f"PAIR{i}", "szi": "1"} for i in range(150)]
        cancelled = []
        closed = []
        report = execute_close_all(
            positions,
            lambda symbol: cancelled.append(symbol) or 1,
            lambda symbol, size: closed.append((symbol, size)),
        )
        self.assertEqual(150, len(report["closed"]))
        self.assertEqual(150, len(cancelled))
        self.assertEqual(150, len(closed))
        self.assertEqual([], report["failed"])

    def test_one_failure_stays_visible_and_other_positions_continue(self):
        positions = [{"coin": "BTC", "szi": "1"}, {"coin": "ETH", "szi": "2"}]

        def close(symbol, _size):
            if symbol == "BTC":
                raise RuntimeError("fake exchange refusal")

        report = execute_close_all(positions, lambda _symbol: 0, close)
        self.assertEqual(["ETH"], report["closed"])
        self.assertEqual("BTC", report["failed"][0]["symbol"])


if __name__ == "__main__":
    unittest.main()
