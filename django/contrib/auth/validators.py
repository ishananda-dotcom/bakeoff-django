import re

from django.core import validators
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class ASCIIUsernameValidator(validators.RegexValidator):
    regex = r"^[\w.@+-]+\Z"
    message = _ (
        "Enter a valid username. This value may contain only unaccented lowercase a-z "
        "and uppercase A-Z letters, numbers, and @/./+/-/_ characters."
    )
    flags = re.ASCII


@deconstructible
class UnicodeUsernameValidator(validators.RegexValidator):
    regex = r"^[\w.@+-]+\Z"
    message = _ (
        "Enter a valid username. This value may contain only letters, "
        "numbers, and @/./+/-/_ characters."
    )
    flags = 0


# Regression tests for UsernameValidator

import unittest

class TestUsernameValidator(unittest.TestCase):
    def test_valid_username(self):
        validator = ASCIIUsernameValidator()
        try:
            validator('valid_username')
        except validators.ValidationError:
            self.fail('ASCIIUsernameValidator raised ValidationError unexpectedly!')

    def test_invalid_username_with_newline(self):
        validator = ASCIIUsernameValidator()
        with self.assertRaises(validators.ValidationError):
            validator('invalid_username
')

    def test_unicode_username(self):
        validator = UnicodeUsernameValidator()
        try:
            validator('valid_username_123')
        except validators.ValidationError:
            self.fail('UnicodeUsernameValidator raised ValidationError unexpectedly!')

if __name__ == '__main__':
    unittest.main()
