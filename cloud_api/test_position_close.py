import unittest

from position_close import close_size


class PositionCloseTest(unittest.TestCase):
    def test_all_four_close_percentages_for_long_and_short_sizes(self):
        for signed_size in (8.0, -8.0):
            self.assertEqual(2.0, close_size(signed_size, 25))
            self.assertEqual(4.0, close_size(signed_size, 50))
            self.assertEqual(6.0, close_size(signed_size, 75))
            self.assertEqual(8.0, close_size(signed_size, 100))

    def test_unsupported_percentage_is_rejected(self):
        with self.assertRaises(ValueError):
            close_size(8.0, 60)


if __name__ == "__main__":
    unittest.main()
