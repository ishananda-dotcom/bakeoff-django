import re

from django.core import validators
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class ASCIIUsernameValidator(validators.RegexValidator):
    regex = r"^[\w.@+-]+\Z"
    message = _(
        "Enter a valid username. This value may contain only unaccented lowercase a-z "
        "and uppercase A-Z letters, numbers, and @/./+/-/_ characters."
    )
    flags = re.ASCII


@deconstructible
class UnicodeUsernameValidator(validators.RegexValidator):
    regex = r"^[\w.@+-]+\Z"
    message = _(
        "Enter a valid username. This value may contain only letters, "
        "numbers, and @/./+/-/_ characters."
    )
    flags = re.UNICODE

# New test cases for username validation
def test_ascii_username_validator():
    validator = ASCIIUsernameValidator()
    assert validator.regex.match('valid_username') is not None
    assert validator.regex.match('invalid username') is None
def test_unicode_username_validator():
    validator = UnicodeUsernameValidator()
    assert validator.regex.match('valid.username') is not None
    assert validator.regex.match('invalid username') is None
