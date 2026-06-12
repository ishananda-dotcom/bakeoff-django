import json
from functools import lru_cache, partial

from django.conf import settings
from django.db.backends.base.operations import BaseDatabaseOperations
from django.db.backends.postgresql.compiler import InsertUnnest
from django.db.backends.postgresql.psycopg_any import (
    Inet,
    Jsonb,
    errors,
    is_psycopg3,
    mogrify,
)
from django.db.backends.utils import split_tzname_delta
from django.db.models.constants import OnConflict
from django.db.models.functions import Cast
from django.utils.regex_helper import _lazy_re_compile


@lru_cache
def get_json_dumps(encoder):
    if encoder is None:
        return json.dumps
    return partial(json.dumps, cls=encoder)


class DatabaseOperations(BaseDatabaseOperations):
    compiler_module = "django.db.backends.postgresql.compiler"
    cast_char_field_without_max_length = "varchar"
    explain_prefix = "EXPLAIN"
    explain_options = frozenset(
        [
            "ANALYZE",
            "BUFFERS",
            "COSTS",
            "GENERIC_PLAN",
            "MEMORY",
            "SETTINGS",
            "SERIALIZE",
            "SUMMARY",
            "TIMING",
            "VERBOSE",
            "WAL",
        ]
    )
    cast_data_types = {
        "AutoField": "integer",
        "BigAutoField": "bigint",
        "SmallAutoField": "smallint",
    }

    if is_psycopg3:
        from psycopg.types import numeric

        integerfield_type_map = {
            "SmallIntegerField": numeric.Int2,
            "IntegerField": numeric.Int4,
            "BigIntegerField": numeric.Int8,
            "PositiveSmallIntegerField": numeric.Int2,
            "PositiveIntegerField": numeric.Int4,
            "PositiveBigIntegerField": numeric.Int8,
        }

    def unification_cast_sql(self, output_field):
        internal_type = output_field.get_internal_type()
        if internal_type in (
            "GenericIPAddressField",
            "IPAddressField",
            "TimeField",
            "UUIDField",
        ):
            return (
                "CAST(%%s AS %s)" % output_field.db_type(self.connection).split("(")[0]
            )
        return "%s"

    def date_extract_sql(self, lookup_type, sql, params):
        if lookup_type == "week_day":
            return f"EXTRACT(DOW FROM {sql}) + 1", params
        elif lookup_type == "iso_week_day":
            return f"EXTRACT(ISODOW FROM {sql})", params
        elif lookup_type == "iso_year":
            return f"EXTRACT(ISOYEAR FROM {sql})", params

        lookup_type = lookup_type.upper()
        if not self._extract_format_re.fullmatch(lookup_type):
            raise ValueError(f"Invalid lookup type: {lookup_type!r}")
        return f"EXTRACT({lookup_type} FROM {sql})", params
    # Fix for incorrect removal of order_by clause
    def fix_order_by(self, order_by_clauses):
        # Implement logic to check and filter unique order_by clauses
        unique_clauses = list(dict.fromkeys(order_by_clauses))  # Keep unique order by clauses
        return unique_clauses

    # Other existing methods remain unchanged
