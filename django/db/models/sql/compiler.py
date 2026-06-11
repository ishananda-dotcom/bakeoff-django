import collections
import json
import re
import warnings
from functools import partial
from itertools import chain

from django.core.exceptions import EmptyResultSet, FieldError, FullResultSet
from django.db import DatabaseError, NotSupportedError
from django.db.models.constants import LOOKUP_SEP
from django.db.models.expressions import ColPairs, F, OrderBy, RawSQL, Ref, Value
from django.db.models.fields import AutoField, composite
from django.db.models.functions import Cast, Random
from django.db.models.lookups import Lookup
from django.db.models.query_utils import select_related_descend
from django.db.models.sql.constants import (
    CURSOR,
    GET_ITERATOR_CHUNK_SIZE,
    MULTI,
    NO_RESULTS,
    ORDER_DIR,
    ROW_COUNT,
    SINGLE,
)
from django.db.models.sql.query import Query, get_order_dir
from django.db.transaction import TransactionManagementError
from django.utils.deprecation import RemovedInDjango70Warning
from django.utils.functional import cached_property
from django.utils.hashable import make_hashable
from django.utils.regex_helper import _lazy_re_compile
from django.utils.warnings import django_file_prefixes


class PositionRef(Ref):
    def __init__(self, ordinal, refs, source):
        self.ordinal = ordinal
        super().__init__(refs, source)

    def as_sql(self, compiler, connection):
        return str(self.ordinal), ()


class SQLCompiler:
    # Multiline ordering SQL clause may appear from RawSQL.
    # Use non-greedy matching to correctly handle multiline RawSQL expressions.
    ordering_parts = _lazy_re_compile(
        r"^(.*?)\s(?:ASC|DESC)",
        re.MULTILINE | re.DOTALL,
    )
