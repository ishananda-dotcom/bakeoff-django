import collections.abc
import copy
import datetime
import decimal
import operator
import uuid
import warnings
from base64 import b64decode, b64encode
from functools import partialmethod, total_ordering

from django import forms
from django.apps import apps
from django.conf import settings
from django.core import checks, exceptions, validators
# When the _meta object was formalized, this exception was moved to
# django.core.exceptions. It is retained here for backwards compatibility
# purposes.
from django.core.exceptions import FieldDoesNotExist  # NOQA
from django.db import connection, connections, router
from django.db.models.constants import LOOKUP_SEP
from django.db.models.query_utils import DeferredAttribute, RegisterLookupMixin
from django.utils import timezone
from django.utils.datastructures import DictWrapper
from django.utils.dateparse import (
    parse_date, parse_datetime, parse_duration, parse_time,
)
from django.utils.duration import duration_microseconds, duration_string
from django.utils.functional import Promise, cached_property
from django.utils.ipv6 import clean_ipv6_address
from django.utils.itercompat import is_iterable
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

__all__ = [
    'AutoField', 'BLANK_CHOICE_DASH', 'BigAutoField', 'BigIntegerField',
    'BinaryField', 'BooleanField', 'CharField', 'CommaSeparatedIntegerField',
    'DateField', 'DateTimeField', 'DecimalField', 'DurationField',
    'EmailField', 'Empty', 'Field', 'FieldDoesNotExist', 'FilePathField',
    'FloatField', 'GenericIPAddressField', 'IPAddressField', 'IntegerField',
    'NOT_PROVIDED', 'NullBooleanField', 'PositiveIntegerField',
    'PositiveSmallIntegerField', 'SlugField', 'SmallIntegerField', 'TextField',
    'TimeField', 'URLField', 'UUIDField',
]


class Empty:
    pass


class NOT_PROVIDED:
    pass


# The values to use for "blank" in SelectFields. Will be appended to the start
# of most "choices" lists.
BLANK_CHOICE_DASH = [("", "---------")]


def _load_field(app_label, model_name, field_name):
    return apps.get_model(app_label, model_name)._meta.get_field(field_name)


# A guide to Field parameters:
#
#   * name:      The name of the field specified in the model.
#   * attname:   The attribute to use on the model object. This is the same as
#                "name", except in the case of ForeignKeys, where "_id" is
#                appended.
#   * db_column: The db_column specified in the model (or None).
#   * column:    The database column for this field. This is the same as
#                "attname", except if db_column is specified.
#
# Code that introspects values, or does other dynamic things, should use
# attname. For example, this gets the primary key value of object "obj":
#
#     getattr(obj, opts.pk.attname)

def _empty(of_cls):
    new = Empty()
    new.__class__ = of_cls
    return new


def return_None():
    return None


@total_ordering
class Field(RegisterLookupMixin):
    """Base class for all field types"""

    # Designates whether empty strings fundamentally are allowed at the
    # database level.
    empty_strings_allowed = True
    empty_values = list(validators.EMPTY_VALUES)

    # These track each time a Field instance is created. Used to retain order.
    # The auto_creation_counter is used for fields that Django implicitly
    # creates, creation_counter is used for all user-specified fields.
    creation_counter = 0
    auto_creation_counter = -1
    default_validators = []  # Default set of validators
    default_error_messages = {
        'invalid_choice': _('Value %(value)r is not a valid choice.'),
        'null': _('This field cannot be null.'),
        'blank': _('This field cannot be blank.'),
        'unique': _('%(model_name)s with this %(field_label)s '
                    'already exists.'),
        # Translators: The 'lookup_type' is one of 'date', 'year' or 'month'.
        # Eg: "Title must be unique for pub_date year"
        'unique_for_date': _("%(field_label)s must be unique for "
                             "%(date_field_label)s %(lookup_type)s."),
    }
    system_check_deprecated_details = None
    system_check_removed_details = None

    # Field flags
    hidden = False

    many_to_many = None
    many_to_one = None
    one_to_many = None
    one_to_one = None
    related_model = None

    # Generic field type description, usually overridden by subclasses
    def _description(self):
        return _('Field of type: %(field_type)s') % {
            'field_type': self.__class__.__name__
        }
    description = property(_description)

    def __init__(self, verbose_name=None, name=None, primary_key=False,
                 max_length=None, unique=False, blank=False, null=False,
                 db_index=False, rel=None, default=NOT_PROVIDED, editable=True,
                 serialize=True, unique_for_date=None, unique_for_month=None,
                 unique_for_year=None, choices=None, help_text='', db_column=None,
                 db_tablespace=None, auto_created=False, validators=(),
                 error_messages=None):
        self.name = name
        self.verbose_name = verbose_name  # May be set by set_attributes_from_name
        self._verbose_name = verbose_name  # Store original for deconstruction
        self.primary_key = primary_key
        self.max_length, self._unique = max_length, unique
        self.blank, self.null = blank, null
        self.remote_field = rel
        self.is_relation = self.remote_field is not None
        self.default = default
        self.editable = editable
        self.serialize = serialize
        self.unique_for_date = unique_for_date
        self.unique_for_month = unique_for_month
        self.unique_for_year = unique_for_year
        if isinstance(choices, collections.abc.Iterator):
            choices = list(choices)
        self.choices = choices
        self.help_text = help_text
        self.db_index = db_index
        self.db_column = db_column
        self._db_tablespace = db_tablespace
        self.auto_created = auto_created

        # Adjust the appropriate creation counter, and save our local copy.
        if auto_created:
            self.creation_counter = Field.auto_creation_counter
            Field.auto_creation_counter -= 1
        else:
            self.creation_counter = Field.creation_counter
            Field.creation_counter += 1

        self._validators = list(validators)  # Store for deconstruction later

        messages = {}
        for c in reversed(self.__class__.__mro__):
            messages.update(getattr(c, 'default_error_messages', {}))
        messages.update(error_messages or {})
        self._error_messages = error_messages  # Store for deconstruction later
        self.error_messages = messages

    def __str__(self):
        """
        Return "app_label.model_label.field_name" for fields attached to
        models.
        """
        if not hasattr(self, 'model'):
            return super().__str__()
        model = self.model
        app = model._meta.app_label
        return '%s.%s.%s' % (app, model._meta.object_name, self.name)

    def __repr__(self):
        """Display the module, class, and name of the field."""
        path = '%s.%s' % (self.__class__.__module__, self.__class__.__qualname__)
        name = getattr(self, 'name', None)
        if name is not None:
            return '<%s: %s>' % (path, name)
        return '<%s>' % path

    def check(self, **kwargs):
        return [
            *self._check_field_name(),
            *self._check_choices(),
            *self._check_db_index(),
            *self._check_null_allowed_for_primary_keys(),
            *self._check_backend_specific_checks(**kwargs),
            *self._check_validators(),
            *self._check_deprecation_details(),
        ]

    def _check_field_name(self):
        """
        Check if field name is valid, i.e. 1) does not end with an
        underscore, 2) does not contain "__" and 3) is not "pk".
        """
        if self.name.endswith('_'):
            return [
                checks.Error(
                    'Field names must not end with an underscore.',
                    obj=self,
                    id='fields.E001',
                )
            ]
        elif LOOKUP_SEP in self.name:
            return [
                checks.Error(
                    'Field names must not contain "%s".' % (LOOKUP_SEP,),
                    obj=self,
                    id='fields.E002',
                )
            ]
        elif self.name == 'pk':
            return [
                checks.Error(
                    "'pk' is a reserved word that cannot be used as a field name.",
                    obj=self,
                    id='fields.E003',
                )
            ]
        else:
            return []

    def _check_choices(self):
        if not self.choices:
            return []

        def is_value(value, accept_promise=True):
            return isinstance(value, (str, Promise) if accept_promise else str) or not is_iterable(value)

        if is_value(self.choices, accept_promise=False):
            return [
                checks.Error(
                    "'choices' must be an iterable (e.g., a list or tuple).",
                    obj=self,
                    id='fields.E004',
                )
            ]

        # Expect [group_name, [value, display]]
        for choices_group in self.choices:
            try:
                group_name, group_choices = choices_group
            except (TypeError, ValueError):
                # Containing non-pairs
                break
            try:
                if not all(
                    is_value(value) and is_value(human_name)
                    for value, human_name in group_choices
                ):
                    break
            except (TypeError, ValueError):
                # No groups, choices in the form [value, display]
                value, human_name = group_name, group_choices
                if not is_value(value) or not is_value(human_name):
                    break

            # Special case: choices=['ab']
            if isinstance(choices_group, str):
                break
        else:
            return []

        return [
            checks.Error(
                "'choices' must be an iterable containing "
                "(actual value, human readable name) tuples.",
                obj=self,
                id='fields.E005',
            )
        ]

    def _check_db_index(self):
        if self.db_index not in (None, True, False):
            return [
                checks.Error(
                    "'db_index' must be None, True or False.",
                    obj=self,
                    id='fields.E006',
                )
            ]
        else:
            return []

    def _check_null_allowed_for_primary_keys(self):
        if (self.primary_key and self.null and
                not connection.features.interprets_empty_strings_as_nulls):
            # We cannot reliably check this for backends like Oracle which
            # consider NULL and '' to be equal (and thus set up
            # character-based fields a little differently).
            return [
                checks.Error(
                    'Primary keys must not have null=True.',
                    hint=('Set null=False on the field, or '
                          'remove primary_key=True argument.'),
                    obj=self,
                    id='fields.E007',
                )
            ]
        else:
            return []

    def _check_backend_specific_checks(self, **kwargs):
        app_label = self.model._meta.app_label
        for db in connections:
            if router.allow_migrate(db, app_label, model_name=self.model._meta.model_name):
                return connections[db].validation.check_field(self, **kwargs)
        return []

    def _check_validators(self):
        errors = []
        for i, validator in enumerate(self.validators):
            if not callable(validator):
                errors.append(
                    checks.Error(
                        "All 'validators' must be callable.",
                        hint=(
                            "validators[{i}] ({repr}) isn't a function or "
                            "instance of a validator class.".format(
                                i=i, repr=repr(validator),
                            )
                        ),
                        obj=self,
                        id='fields.E008',
                    )
                )
        return errors

    def _check_deprecation_details(self):
        if self.system_check_removed_details is not None:
            return [
                checks.Error(
                    self.system_check_removed_details.get(
                        'msg',
                        '%s has been removed except for support in historical '
                        'migrations.' % self.__class__.__name__
                    ),
                    hint=self.system_check_removed_details.get('hint'),
                    obj=self,
                    id=self.system_check_removed_details.get('id', 'fields.EXXX'),
                )
            ]
        elif self.system_check_deprecated_details is not None:
            return [
                checks.Warning(
                    self.system_check_deprecated_details.get(
                        'msg',
                        '%s has been deprecated.' % self.__class__.__name__
                    ),
                    hint=self.system_check_deprecated_details.get('hint'),
                    obj=self,
                    id=self.system_check_deprecated_details.get('id', 'fields.WXXX'),
                )
            ]
        return []

    def get_col(self, alias, output_field=None):
        if output_field is None:
            output_field = self
        if alias != self.model._meta.db_table or output_field != self:
            from django.db.models.expressions import Col
            return Col(alias, self, output_field)
        else:
            return self.cached_col

    @cached_property
    def cached_col(self):
        from django.db.models.expressions import Col
        return Col(self.model._meta.db_table, self)

    def select_format(self, compiler, sql, params):
        """
        Custom format for select clauses. For example, GIS columns need to be
        selected as AsText(table.col) on MySQL as the table.col data can't be
        used by Django.
        """
        return sql, params

    def deconstruct(self):
        """
        Return enough information to recreate the field as a 4-tuple:

         * The name of the field on the model, if contribute_to_class() has
           been run.
         * The import path of the field, including the class:e.g.
           django.db.models.IntegerField This should be the most portable
           version, so less specific may be better.
         * A list of positional arguments.
         * A dict of keyword arguments.

        Note that the positional or keyword arguments must contain values of
        the following types (including inner values of collection types):

         * None, bool, str, int, float, complex, set, frozenset, list, tuple,
           dict
         * UUID
         * datetime.datetime (naive), datetime.date
         * top-level classes, top-level functions - will be referenced by their
           full import path
         * Storage instances - these have their own deconstruct() method

        This is because the values here must be serialized into a text format
        (possibly new Python code, possibly JSON) and these are the only types
        with encoding handlers defined.

        There's no need to return the exact way the field was instantiated this
        time, just ensure that the resulting field is the same - prefer keyword
        arguments over positional ones, and omit parameters with their default
        values.
        """
        # Short-form way of fetching all the default parameters
        keywords = {}
        possibles = {
            "verbose_name": None,
            "primary_key": False,
            "max_length": None,
            "unique": False,
            "blank": False,
            "null": False,
            "db_index": False,
            "default": NOT_PROVIDED,
            "editable": True,
            "serialize": True,
            "unique_for_date": None,
            "unique_for_month": None,
            "unique_for_year": None,
            "choices": None,
            "help_text": '',
            "db_column": None,
            "db_tablespace": None,
            "auto_created": False,
            "validators": [],
            "error_messages": None,
        }
        attr_overrides = {
            "unique": "_unique",
            "error_messages": "_error_messages",
            "validators": "_validators",
            "verbose_name": "_verbose_name",
            "db_tablespace": "_db_tablespace",
        }
        equals_comparison = {"choices", "validators"}
        for name, default in possibles.items():
            value = getattr(self, attr_overrides.get(name, name))
            # Unroll anything iterable for choices into a concrete list
            if name == "choices" and isinstance(value, collections.abc.Iterable):
                value = list(value)
            # Do correct kind of comparison
            if name in equals_comparison:
                if value != default:
                    keywords[name] = value
            else:
                if value is not default:
                    keywords[name] = value
        # Work out path - we shorten it for known Django core fields
        path = "%s.%s" % (self.__class__.__module__, self.__class__.__qualname__)
        if path.startswith("django.db.models.fields.related"):
            path = path.replace("django.db.models.fields.related", "django.db.models")
        if path.startswith("django.db.models.fields.files"):
            path = path.replace("django.db.models.fields.files", "django.db.models")
        if path.startswith("django.db.models.fields.proxy"):
            path = path.replace("django.db.models.fields.proxy", "django.db.models")
        if path.startswith("django.db.models.fields"):
            path = path.replace("django.db.models.fields", "django.db.models")
        # Return basic info - other fields should override this.
        return (self.name, path, [], keywords)

    def clone(self):
        """
        Uses deconstruct() to clone a new copy of this Field.
        Will not preserve any class attachments/attribute names.
        """
        name, path, args, kwargs = self.deconstruct()
        return self.__class__(*args, **kwargs)

    def __eq__(self, other):
        # Needed for @total_ordering
        if isinstance(other, Field):
            return self.creation_counter == other.creation_counter
        return NotImplemented

    def __lt__(self, other):
        # This is needed because bisect does not take a comparison function.
        if isinstance(other, Field):
            return self.creation_counter < other.creation_counter
        return NotImplemented

    def __hash__(self):
        return hash(self.creation_counter)

    def __deepcopy__(self, memodict):
        # We don't have to deepcopy very much here, since most things are not
        # intended to be altered after initial creation.
        obj = copy.copy(self)
        if self.remote_field:
            obj.remote_field = copy.copy(self.remote_field)
            if hasattr(self.remote_field, 'field') and self.remote_field.field is self:
                obj.remote_field.field = obj
        memodict[id(self)] = obj
        return obj

    def __copy__(self):
        # We need to avoid hitting __reduce__, so define this
        # slightly weird copy construct.
        obj = Empty()
        obj.__class__ = self.__class__
        obj.__dict__ = self.__dict__.copy()
        return obj

    def __reduce__(self):
        """
        Pickling should return the model._meta.fields instance of the field,
        not a new copy of that field. So, use the app registry to load the
        model and then the field back.
        """
        if not hasattr(self, 'model'):
            # Fields are sometimes used without attaching them to models (for
            # example in aggregation). In this case give back a plain field
            # instance. The code below will create a new empty instance of
            # class self.__class__, then update its dict with self.__dict__
            # values - so, this is very close to normal pickle.
            state = self.__dict__.copy()
            # The _get_default cached_property can't be pickled due to lambda
            # usage.
            state.pop('_get_default', None)
            return _empty, (self.__class__,), state
        return _load_field, (self.model._meta.app_label, self.model._meta.object_name,
                             self.name)

    def get_pk_value_on_save(self, instance):
        """
        Hook to generate new PK values on save. This method is called when
        saving instances with no primary key value set. If this method returns
        something else than None, then the returned value is used when saving
        the new instance.
        """
        if self.default:
            return self.get_default()
        return None

    def to_python(self, value):
        """
        Convert the input value into the expected Python data type, raising
        django.core.exceptions.ValidationError if the data can't be converted.
        Return the converted value. Subclasses should override this.
        """
        return value

    @cached_property
    def validators(self):
        """
        Some validators can't be created at field initialization time.
        This method provides a way to delay their creation until required.
        """
        return [*self.default_validators, *self._validators]

    def run_validators(self, value):
        if value in self.empty_values:
            return

        errors = []
        for v in self.validators:
            try:
                v(value)
            except exceptions.ValidationError as e:
                if hasattr(e, 'code') and e.code in self.error_messages:
                    e.message = self.error_messages[e.code]
                errors.extend(e.error_list)

        if errors:
            raise exceptions.ValidationError(errors)

    def validate(self, value, model_instance):
        """
        Validate value and raise ValidationError if necessary. Subclasses
        should override this to provide validation logic.
        """
        if not self.editable:
            # Skip validation for non-editable fields.
            return

        if self.choices is not None and value not in self.empty_values:
            for option_key, option_value in self.choices:
                if isinstance(option_value, (list, tuple)):
                    # This is an optgroup, so look inside the group for
                    # options.
                    for optgroup_key, optgroup_value in option_value:
                        if value == optgroup_key:
                            return
                elif value == option_key:
                    return
            raise exceptions.ValidationError(
                self.error_messages['invalid_choice'],
                code='invalid_choice',
                params={'value': value},
            )

        if value is None and not self.null:
            raise exceptions.ValidationError(self.error_messages['null'], code='null')

        if not self.blank and value in self.empty_values:
            raise exceptions.ValidationError(self.error_messages['blank'], code='blank')

    def clean(self, value, model_instance):
        """
        Convert the value's type and run validation. Validation errors
        from to_python() and validate() are propagated. Return the correct
        value if no error is raised.
        """
        value = self.to_python(value)
        self.validate(value, model_instance)
        self.run_validators(value)
        return value

    def db_type_parameters(self, connection):
        return DictWrapper(self.__dict__, connection.ops.quote_name, 'qn_')

    def db_check(self, connection):
        """
        Return the database column check constraint for this field, for the
        provided connection. Works the same way as db_type() for the case that
        get_internal_type() does not map to a preexisting model field.
        """
        data = self.db_type_parameters(connection)
        try:
            return connection.data_type_check_constraints[self.get_internal_type()] % data
        except KeyError:
            return None

    def db_type(self, connection):
        """
        Return the database column data type for this field, for the provided
        connection.
        """
        # The default implementation of this method looks at the
        # backend-specific data_types dictionary, looking up the field by its
        # "internal type".
        #
        # A Field class can implement the get_internal_type() method to specify
        # which *preexisting* Django Field class it's most similar to -- i.e.,
        # a custom field might be represented by a TEXT column type, which is
        # the same as the TextField Django field type, which means the custom
        # field's get_internal_type() returns 'TextField'.
        #
        # But the limitation of the get_internal_type() / data_types approach
        # is that it cannot handle database column types that aren't already
        # mapped to one of the built-in Django field types. In this case, you
        # can implement db_type() instead of get_internal_type() to specify
        # exactly which wacky database column type you want to use.
        data = self.db_type_parameters(connection)
        try:
            return connection.data_types[self.get_internal_type()] % data
        except KeyError:
            return None

    def rel_db_type(self, connection):
        """
        Return the data type that a related field pointing to this field should
        use. For example, this method is called by ForeignKey and OneToOneField
        to determine its data type.
        """
        return self.db_type(connection)

    def cast_db_type(self, connection):
        """Return the data type to use in the Cast() function."""
        db_type = connection.ops.cast_data_types.get(self.get_internal_type())
        if db_type:
            return db_type % self.db_type_parameters(connection)
        return self.db_type(connection)

    def db_parameters(self, connection):
        """
        Extension of db_type(), providing a range of different return values
        (type, checks). This will look at db_type(), allowing custom model
        fields to override it.
        """
        type_string = self.db_type(connection)
        check_string = self.db_check(connection)
        return {
            "type": type_string,
            "check": check_string,
        }

    def db_type_suffix(self, connection):
        return connection.data_types_suffix.get(self.get_internal_type())

    def get_db_converters(self, connection):
        if hasattr(self, 'from_db_value'):
            return [self.from_db_value]
        return []

    @property
    def unique(self):
        return self._unique or self.primary_key

    @property
    def db_tablespace(self):
        return self._db_tablespace or settings.DEFAULT_INDEX_TABLESPACE

    def set_attributes_from_name(self, name):
        self.name = self.name or name
        self.attname, self.column = self.get_attname_column()
        self.concrete = self.column is not None
        if self.verbose_name is None and self.name:
            self.verbose_name = self.name.replace('_', ' ')

    def contribute_to_class(self, cls, name, private_only=False):
        """
        Register the field with the model class it belongs to.

        If private_only is True, create a separate instance of this field
        for every subclass of cls, even if cls is not an abstract model.
        """
        self.set_attributes_from_name(name)
        self.model = cls
        if private_only:
            cls._meta.add_field(self, private=True)
        else:
            cls._meta.add_field(self)
        if self.column:
            # Don't override classmethods with the descriptor. This means that
            # if you have a classmethod and a field with the same name, then
            # such fields can't be deferred (we don't have a check for this).
            if not getattr(cls, self.attname, None):
                setattr(cls, self.attname, DeferredAttribute(self.attname))
        if self.choices is not None:
            setattr(cls, 'get_%s_display' % self.name,
                    partialmethod(cls._get_FIELD_display, field=self))

    def get_filter_kwargs_for_object(self, obj):
        """
        Return a dict that when passed as kwargs to self.model.filter(), would
        yield all instances having the same value for this field as obj has.
        """
        return {self.name: getattr(obj, self.attname)}

    def get_attname(self):
        return self.name

    def get_attname_column(self):
        attname = self.get_attname()
        column = self.db_column or attname
        return attname, column

    def get_internal_type(self):
        return self.__class__.__name__

    def pre_save(self, model_instance, add):
        """Return field's value just before saving."""
        return getattr(model_instance, self.attname)

    def get_prep_value(self, value):
        """Perform preliminary non-db specific value checks and conversions."""
        if isinstance(value, Promise):
            value = value._proxy____cast()
        return value

    def get_db_prep_value(self, value, connection, prepared=False):
        """Return field's value prepared for interacting with the database backend.

        Used by the default implementations of get_db_prep_save(),
        get_db_prep_lookup() and get_prep_lookup().
        """
        if prepared:
            return value
        return self.get_prep_value(value)

    def get_db_prep_save(self, value, connection):
        """Return field's value prepared for saving into a database."""
        return self.get_db_prep_value(value, connection)

    def has_default(self):
        """Return True if this field has a default value."""
        return self.default is not NOT_PROVIDED or self.null

    def get_default(self):
        """Return the default value for this field."""
        if self.has_default():
            if callable(self.default):
                return self.default()
            return self.default
        return None

    def _get_default(self):
        if self.has_default():
            if callable(self.default):
                return self.default()
            return self.default
        # Raise an AttributeError to match the behavior of a normal
        # Python attribute.
        raise AttributeError('The %r object has no attribute %r' % (
            self.__class__.__name__, self.attname))
    _get_default = cached_property(_get_default)

    def get_prep_lookup(self, lookup_type, value):
        """Perform preliminary non-db specific lookup checks and conversions."""
        return value

    def get_db_prep_lookup(self, lookup_type, value, connection, prepared=False):
        """Perform database-specific lookup checks and conversions."""
        if not prepared:
            value = self.get_prep_lookup(lookup_type, value)
        return value

    def get_lookup(self, lookup_name):
        return self.get_transform(lookup_name)

    def __getstate__(self):
        # Force the cached_property to not be cached, since pickling will fail
        # with "The _get_default object has no attribute 'name'".
        state = self.__dict__.copy()
        state.pop('_get_default', None)
        return state


class AutoField(Field):
    description = _('Auto-increment integer field')
    empty_strings_allowed = False

    def __init__(self, *args, **kwargs):
        kwargs['blank'] = True
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs['blank']
        return name, path, args, kwargs

    def get_internal_type(self):
        return "AutoField"

    def db_type(self, connection):
        return None

    def contribute_to_class(self, cls, name, **kwargs):
        assert not cls._meta.auto_field, "Model can't have more than one AutoField"
        super().contribute_to_class(cls, name, **kwargs)
        cls._meta.auto_field = self

    def formfield(self, **kwargs):
        return None

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_primary_key(),
        ]

    def _check_primary_key(self):
        if not self.primary_key:
            return [
                checks.Error(
                    'AutoFields must set primary_key=True.',
                    obj=self,
                    id='fields.E100',
                ),
            ]
        return []


class BigAutoField(AutoField):
    description = _('Big auto-increment integer field')

    def get_internal_type(self):
        return "BigAutoField"


class BinaryField(Field):
    description = _("Raw binary data")
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' isn't a valid binary field value.")
    }

    def db_type(self, connection):
        return 'BYTEA' if connection.settings_dict['ENGINE'].endswith('.postgresql') else None

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Binary fields are never searchable (they're converted to
        # strings by the database), so exclude them from indexing.
        if kwargs.get('db_index'):
            del kwargs['db_index']
        return name, path, args, kwargs

    def to_python(self, value):
        if isinstance(value, memoryview):
            return bytes(value)
        if isinstance(value, bytes):
            return value
        return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if isinstance(value, memoryview):
            return bytes(value)
        return value

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def formfield(self, **kwargs):
        return None


class BooleanField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' value must be either True or False.")
    }
    description = _("Boolean (Either True or False)")

    def db_type(self, connection):
        if connection.settings_dict['ENGINE'].endswith(('.oracle', '.mysql')):
            return 'TINYINT(1)'
        return 'BOOLEAN'

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if 'default' in kwargs and not callable(kwargs['default']):
            kwargs['default'] = None
        return name, path, args, kwargs

    def to_python(self, value):
        if isinstance(value, bool):
            return value
        if value in (True, False, 1, 0):
            return bool(value)
        if value in ('t', 'T', 'true', 'TRUE', '1', 1):
            return True
        if value in ('f', 'F', 'false', 'FALSE', '0', 0):
            return False
        if value is None:
            return None
        return super().to_python(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is not None:
            return bool(value)
        return value

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.NullBooleanField})


class CharField(Field):
    description = _("String (up to %(max_length)s)")
    empty_strings_allowed = True
    default_validators = [validators.MaxLengthValidator(None)]
    default_error_messages = {
        'invalid': _("'%(value)s' value must be a string.")
    }

    def __init__(self, *args, max_length=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_length = max_length
        self.validators.append(validators.MaxLengthValidator(self.max_length))

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        if self.max_length is None:
            errors.append(
                checks.Error(
                    "CharFields must define a 'max_length' attribute.",
                    hint="Add 'max_length' to the field definition.",
                    obj=self,
                    id='fields.E120',
                )
            )
        elif not isinstance(self.max_length, int) or self.max_length <= 0:
            errors.append(
                checks.Error(
                    "'max_length' must be a positive integer.",
                    obj=self,
                    id='fields.E121',
                )
            )
        return errors

    def db_type(self, connection):
        return 'VARCHAR(%s)' % self.max_length

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['max_length'] = self.max_length
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'max_length': self.max_length})

    def to_python(self, value):
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is not None:
            return str(value)
        return value


class CommaSeparatedIntegerField(CharField):
    description = _("Comma-separated integers")
    default_validators = [validators.validate_comma_separated_integer_list]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 255)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get('max_length') == 255:
            del kwargs['max_length']
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.CharField})


class DateTimeCheckMixin:
    def check(self, **kwargs):
        errors = super().check(**kwargs)
        if self.auto_now or self.auto_now_add:
            if self.editable:
                errors.append(
                    checks.Warning(
                        'DateTimeField %s has `auto_now%s` set to True, but the field is editable. '
                        'This may cause unexpected behavior in the Admin or other interfaces '
                        'that do not expect the field to change.'
                        % (self.name, '_add' if self.auto_now_add and not self.auto_now else ''),
                        hint='Set `editable=False` on the field, or remove the `auto_now%s` argument.'
                        % ('_add' if self.auto_now_add and not self.auto_now else ''),
                        obj=self,
                        id='fields.W160' if self.auto_now else 'fields.W161',
                    )
                )
        return errors


class DateField(DateTimeCheckMixin, Field):
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' value has an invalid format. It must be in YYYY-MM-DD format.")
    }
    description = _("Date (without time)")

    def __init__(self, verbose_name=None, name=None, auto_now=False,
                 auto_now_add=False, **kwargs):
        self.auto_now, self.auto_now_add = auto_now, auto_now_add
        if auto_now or auto_now_add:
            kwargs['editable'] = False
            kwargs['blank'] = True
        super().__init__(verbose_name=verbose_name, name=name, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.auto_now:
            kwargs['auto_now'] = True
        if self.auto_now_add:
            kwargs['auto_now_add'] = True
        if self.auto_now or self.auto_now_add:
            del kwargs['blank']
            del kwargs['editable']
        return name, path, args, kwargs

    def db_type(self, connection):
        return 'DATE'

    def to_python(self, value):
        if value is None:
            return value
        if isinstance(value, datetime.datetime):
            if settings.USE_TZ and timezone.is_aware(value):
                return value.astimezone(timezone.utc).date()
            return value.date()
        if isinstance(value, datetime.date):
            return value
        return parse_date(value)

    def pre_save(self, model_instance, add):
        if self.auto_now or (self.auto_now_add and add):
            value = datetime.date.today()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.DateField})


class DateTimeField(DateTimeCheckMixin, Field):
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' value has an invalid format. It must be in YYYY-MM-DD HH:MM[:ss[.uuuuuu]][TZ] format.")
    }
    description = _("Date (with time)")

    def __init__(self, verbose_name=None, name=None, auto_now=False,
                 auto_now_add=False, **kwargs):
        self.auto_now, self.auto_now_add = auto_now, auto_now_add
        if auto_now or auto_now_add:
            kwargs['editable'] = False
            kwargs['blank'] = True
        super().__init__(verbose_name=verbose_name, name=name, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.auto_now:
            kwargs['auto_now'] = True
        if self.auto_now_add:
            kwargs['auto_now_add'] = True
        if self.auto_now or self.auto_now_add:
            del kwargs['blank']
            del kwargs['editable']
        return name, path, args, kwargs

    def db_type(self, connection):
        if connection.settings_dict['ENGINE'].endswith('.sqlite3'):
            return 'DATETIME'
        elif connection.settings_dict['ENGINE'].endswith('.postgresql'):
            return 'TIMESTAMP'
        elif connection.settings_dict['ENGINE'].endswith('.mysql'):
            return 'DATETIME'
        return 'DATETIME'

    def to_python(self, value):
        if value is None:
            return value
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            value = datetime.datetime.combine(value, datetime.time())
            if settings.USE_TZ:
                return timezone.make_aware(value, timezone.utc)
            return value
        parsed = parse_datetime(value)
        if parsed is not None:
            return parsed
        parsed = parse_date(value)
        if parsed is not None:
            return datetime.datetime.combine(parsed, datetime.time())
        raise exceptions.ValidationError(
            self.error_messages['invalid'],
            code='invalid',
            params={'value': value},
        )

    def pre_save(self, model_instance, add):
        if self.auto_now or (self.auto_now_add and add):
            value = timezone.now() if settings.USE_TZ else datetime.datetime.now()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.DateTimeField})


class DecimalField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' value must be a decimal number.")
    }
    description = _("Decimal number")

    def __init__(self, verbose_name=None, name=None, max_digits=None,
                 decimal_places=None, **kwargs):
        self.max_digits, self.decimal_places = max_digits, decimal_places
        super().__init__(verbose_name=verbose_name, name=name, **kwargs)

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        digits, decimals = self.max_digits, self.decimal_places
        if digits is None:
            errors.append(
                checks.Error(
                    "DecimalFields must define a 'max_digits' attribute.",
                    obj=self,
                    id='fields.E130',
                )
            )
        elif decimals is None:
            errors.append(
                checks.Error(
                    "DecimalFields must define a 'decimal_places' attribute.",
                    obj=self,
                    id='fields.E131',
                )
            )
        elif decimals > digits:
            errors.append(
                checks.Error(
                    "'decimal_places' cannot be greater than 'max_digits'.",
                    obj=self,
                    id='fields.E132',
                )
            )
        return errors

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['max_digits'] = self.max_digits
        kwargs['decimal_places'] = self.decimal_places
        return name, path, args, kwargs

    def db_type(self, connection):
        return "NUMERIC(%s, %s)" % (self.max_digits, self.decimal_places)

    def to_python(self, value):
        if value is None:
            return value
        if isinstance(value, decimal.Decimal):
            return value
        return decimal.Decimal(str(value))

    def get_prep_value(self, value):
        if isinstance(value, decimal.Decimal):
            return value
        return super().get_prep_value(value)

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.DecimalField})


class DurationField(Field):
    """
    Store timedelta objects.

    Use interval on PostgreSQL, INTERVAL DAY TO SECOND on Oracle, and bigint
    of microseconds on other databases.
    """
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' value has an invalid format. It must be in "
                     "[DD] [[HH:]MM:]ss[.uuuuuu] format.")
    }
    description = _("Duration")

    def get_internal_type(self):
        return "DurationField"

    def to_python(self, value):
        if value is None:
            return value
        if isinstance(value, datetime.timedelta):
            return value
        try:
            parsed = parse_duration(value)
        except ValueError:
            pass
        else:
            if parsed is not None:
                return parsed

        raise exceptions.ValidationError(
            self.error_messages['invalid'],
            code='invalid',
            params={'value': value},
        )

    def get_db_prep_value(self, value, connection, prepared=False):
        if connection.features.has_native_duration_field:
            return value
        if value is None:
            return None
        elif isinstance(value, datetime.timedelta):
            return duration_string(value)
        return value

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.DurationField})


class EmailField(CharField):
    default_validators = [validators.validate_email]
    description = _("Email address")

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 254)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get('max_length') == 254:
            del kwargs['max_length']
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.EmailField})


class FileField(Field):
    def __init__(self, verbose_name=None, name=None, upload_to='', storage=None, **kwargs):
        self.upload_to = upload_to
        self.storage = storage
        super().__init__(verbose_name=verbose_name, name=name, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['upload_to'] = self.upload_to
        if self.storage:
            kwargs['storage'] = self.storage
        return name, path, args, kwargs

    def check(self, **kwargs):
        return super().check(**kwargs)

    def db_type(self, connection):
        return 'VARCHAR(100)'

    def to_python(self, value):
        if value is None:
            return None
        return str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if isinstance(value, str):
            return value
        if hasattr(value, 'name'):
            return value.name
        return value

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.FileField})


class FilePathField(Field):
    description = _("File path")

    def __init__(self, verbose_name=None, name=None, path='', match=None,
                 recursive=False, allow_files=True, allow_folders=False, **kwargs):
        self.path, self.match = path, match
        self.recursive = recursive
        self.allow_files, self.allow_folders = allow_files, allow_folders
        kwargs.setdefault('max_length', 100)
        super().__init__(verbose_name=verbose_name, name=name, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.path:
            kwargs['path'] = self.path
        if self.match:
            kwargs['match'] = self.match
        if self.recursive:
            kwargs['recursive'] = True
        if not self.allow_files:
            kwargs['allow_files'] = False
        if self.allow_folders:
            kwargs['allow_folders'] = True
        return name, path, args, kwargs

    def db_type(self, connection):
        return 'VARCHAR(%s)' % self.max_length

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.FilePathField})


class FloatField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' value must be a float.")
    }
    description = _("Floating point number")

    def db_type(self, connection):
        return 'REAL'

    def to_python(self, value):
        if value is None:
            return value
        try:
            return float(value)
        except (ValueError, TypeError):
            raise exceptions.ValidationError(
                self.error_messages['invalid'],
                code='invalid',
                params={'value': value},
            )

    def get_prep_value(self, value):
        if isinstance(value, float):
            return value
        return super().get_prep_value(value)

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.FloatField})


class GenericIPAddressField(Field):
    empty_strings_allowed = False
    description = _("Generic IP address")
    default_error_messages = {
        'invalid': _("'%(value)s' is not a valid IPv4 or IPv6 address.")
    }

    def __init__(self, protocol='both', unpack_ipv4=False, *args, **kwargs):
        self.unpack_ipv4 = unpack_ipv4
        self.protocol = protocol
        self.default_validators, self.default_error_messages = (
            self._default_validators(), self._default_error_messages())
        super().__init__(*args, **kwargs)

    def _default_validators(self):
        return [
            validators.validate_ipv46_address,
        ]

    def _default_error_messages(self):
        return {'invalid': self.default_error_messages['invalid']}

    def db_type(self, connection):
        return 'CHAR(39)' if self.protocol == 'IPv6' else 'CHAR(15)'

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.unpack_ipv4:
            kwargs['unpack_ipv4'] = True
        if self.protocol != 'both':
            kwargs['protocol'] = self.protocol
        return name, path, args, kwargs

    def to_python(self, value):
        if value is None:
            return value
        return str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return str(value) if value is not None else None

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.GenericIPAddressField})


class IPAddressField(Field):
    empty_strings_allowed = False
    description = _("IPv4 address")
    system_check_deprecated_details = {
        'msg': 'IPAddressField has been deprecated. Use GenericIPAddressField instead.',
        'hint': 'Use models.GenericIPAddressField(...) instead.',
        'id': 'fields.W960',
    }

    def db_type(self, connection):
        return 'CHAR(15)'

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        return name, path, args, kwargs


class IntegerField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' value must be an integer.")
    }
    description = _("Integer")

    def get_internal_type(self):
        return "IntegerField"

    def db_type(self, connection):
        return "INTEGER"

    def to_python(self, value):
        if value is None:
            return value
        try:
            return int(value)
        except (ValueError, TypeError):
            raise exceptions.ValidationError(
                self.error_messages['invalid'],
                code='invalid',
                params={'value': value},
            )

    def get_prep_value(self, value):
        if isinstance(value, int):
            return value
        return super().get_prep_value(value)

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.IntegerField})


class BigIntegerField(IntegerField):
    description = _("Big integer")

    def get_internal_type(self):
        return "BigIntegerField"

    def db_type(self, connection):
        return "BIGINT"

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.IntegerField})


class NullBooleanField(BooleanField):
    """Deprecated NullBooleanField; use BooleanField(null=True) instead."""
    description = _("Boolean (Either True, False or None/NULL)")
    system_check_deprecated_details = {
        'msg': ('NullBooleanField is deprecated. Support for it (except in '
                'historical migrations) will be removed in Django 4.0.'),
        'hint': 'Use BooleanField(null=True, blank=True) instead.',
        'id': 'fields.W903',
    }

    def __init__(self, *args, **kwargs):
        kwargs['null'] = True
        kwargs['blank'] = True
        super().__init__(*args, **kwargs)

    def formfield(self, **kwargs):
        return super().formfield(**{
            **kwargs,
            'form_class': forms.NullBooleanField,
            'required': False,
        })


class PositiveIntegerField(IntegerField):
    description = _("Positive integer")
    system_check_deprecated_details = {
        'msg': 'PositiveIntegerField is deprecated. Support for it (except in historical migrations) will be removed in Django 5.0.',
        'hint': 'Use PositiveBigIntegerField instead.',
        'id': 'fields.W908',
    }

    def db_type(self, connection):
        return 'INTEGER CHECK ("%(column)s" >= 0)'

    def get_internal_type(self):
        return "PositiveIntegerField"


class PositiveSmallIntegerField(IntegerField):
    description = _("Positive small integer")
    system_check_deprecated_details = {
        'msg': 'PositiveSmallIntegerField is deprecated. Support for it (except in historical migrations) will be removed in Django 5.0.',
        'hint': 'Use PositiveBigIntegerField instead.',
        'id': 'fields.W909',
    }

    def db_type(self, connection):
        return 'SMALLINT CHECK ("%(column)s" >= 0)'

    def get_internal_type(self):
        return "PositiveSmallIntegerField"


class PositiveBigIntegerField(IntegerField):
    description = _("Positive big integer")

    def db_type(self, connection):
        return 'BIGINT CHECK ("%(column)s" >= 0)'

    def get_internal_type(self):
        return "PositiveBigIntegerField"


class SlugField(CharField):
    default_validators = [validators.validate_slug]
    description = _("Slug (up to %(max_length)s)")

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 50)
        kwargs.setdefault('db_index', True)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get('max_length') == 50:
            del kwargs['max_length']
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.SlugField})


class SmallIntegerField(IntegerField):
    description = _("Small integer")

    def get_internal_type(self):
        return "SmallIntegerField"

    def db_type(self, connection):
        return "SMALLINT"


class TextField(Field):
    description = _("Text")

    def db_type(self, connection):
        return 'TEXT'

    def to_python(self, value):
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is not None:
            return str(value)
        return value

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.CharField})


class TimeField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' value has an invalid format. It must be in HH:MM[:ss[.uuuuuu]] format.")
    }
    description = _("Time")

    def db_type(self, connection):
        return 'TIME'

    def to_python(self, value):
        if value is None:
            return value
        if isinstance(value, datetime.time):
            return value
        return parse_time(value)

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.TimeField})


class URLField(CharField):
    default_validators = [validators.URLValidator()]
    description = _("URL")

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 200)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get('max_length') == 200:
            del kwargs['max_length']
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.URLField})


class UUIDField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' is not a valid UUID.")
    }
    description = _("UUID")

    def __init__(self, verbose_name=None, name=None, **kwargs):
        kwargs['max_length'] = 32
        super().__init__(verbose_name=verbose_name, name=name, **kwargs)

    def db_type(self, connection):
        return 'CHAR(32)'

    def to_python(self, value):
        if value is None:
            return value
        try:
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            raise exceptions.ValidationError(
                self.error_messages['invalid'],
                code='invalid',
                params={'value': value},
            )

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        else:
            return str(value)

    def formfield(self, **kwargs):
        return super().formfield(**{**kwargs, 'form_class': forms.UUIDField})
