from django.db.models.sql.compiler import (  # isort:skip
    SQLAggregateCompiler,
    SQLCompiler,
    SQLDeleteCompiler,
    SQLInsertCompiler as BaseSQLInsertCompiler,
    SQLUpdateCompiler,
)

__all__ = [
    "SQLAggregateCompiler",
    "SQLCompiler",
    "SQLDeleteCompiler",
    "SQLInsertCompiler",
    "SQLUpdateCompiler",
]


class InsertUnnest(list):
    """
    Sentinel value to signal DatabaseOperations.bulk_insert_sql() that the
    UNNEST strategy should be used for the bulk insert.
    """

    def __str__(self):
        return "UNNEST(%s)" % ", ".join(self)


class SQLInsertCompiler(BaseSQLInsertCompiler):
    def assemble_as_sql(self, fields, value_rows):
        # Specialize bulk-insertion of literal values through UNNEST to
        # reduce the time spent planning the query.
        if (
            len(value_rows) <= 1
            or any(field is None for field in fields)
            or any(hasattr(field, "get_placeholder_sql") for field in fields)
            or any(
                (field.target_field if field.is_relation else field).get_internal_type()
                not in self.connection.data_types
                for field in fields
            )
            or any(any(hasattr(value, "as_sql") for value in row) for row in value_rows)
        ):
            return super().assemble_as_sql(fields, value_rows)

        db_types = [field.db_type(self.connection).split("(")[0] for field in fields]
        return InsertUnnest(["(%%s)::%s[]" % db_type for db_type in db_types]), [
            list(map(list, zip(*value_rows)))
        ]
        # Fix for incorrect removal of order_by clause
        # Refer to the new fix_order_by method in DatabaseOperations to ensure that
        # unique order_by clauses are handled correctly during SQL compilation
