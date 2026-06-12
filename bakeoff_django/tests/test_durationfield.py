import unittest
from bakeoff_django.models import DurationField

class TestDurationField(unittest.TestCase):
    def test_invalid_duration_format(self):
        with self.assertRaises(ValueError):
            DurationField().clean('invalid_duration')

    def test_valid_duration_format(self):
        result = DurationField().clean('00:30:00')
        self.assertEqual(result, '00:30:00')

if __name__ == '__main__':
    unittest.main()