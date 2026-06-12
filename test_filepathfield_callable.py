"""
Test for FilePathField with callable path support.

This test demonstrates that FilePathField now supports callable paths
for dynamic path resolution based on environment.
"""
import os
import tempfile
from django.db import models
from django.conf import settings


def get_dynamic_path():
    """
    Example callable that returns a dynamic path.
    This allows different paths on different machines/environments.
    """
    return os.path.join(settings.BASE_DIR, 'files')


class ExampleModel(models.Model):
    """
    Example model using FilePathField with a callable path.

    The path is resolved at runtime, allowing different paths
    on different machines (dev, staging, production).
    """
    # String path (traditional usage)
    file_static = models.FilePathField(
        path='/static/files',
        allow_files=True,
        allow_folders=False,
    )

    # Callable path (new feature)
    file_dynamic = models.FilePathField(
        path=get_dynamic_path,  # Callable that returns path at runtime
        allow_files=True,
        allow_folders=False,
    )

    class Meta:
        app_label = 'test_app'


def test_filepathfield_with_callable():
    """Test that FilePathField properly handles callable paths."""
    # Create an instance of the model
    instance = ExampleModel()

    # Get the field
    field = ExampleModel._meta.get_field('file_dynamic')

    # Verify the field has a callable path
    assert callable(field.path), "FilePathField.path should be callable"

    # Get the form field
    form_field = field.formfield()

    # Verify the form field has the resolved path
    expected_path = get_dynamic_path()
    assert form_field.path == expected_path, \
        f"Form field path should be {expected_path}, got {form_field.path}"

    print("✓ FilePathField with callable path works correctly")


def test_filepathfield_with_string():
    """Test that FilePathField still works with string paths."""
    # Get the field
    field = ExampleModel._meta.get_field('file_static')

    # Verify the field has a string path
    assert isinstance(field.path, str), "FilePathField.path should be a string"
    assert not callable(field.path), "FilePathField.path should not be callable"

    # Get the form field
    form_field = field.formfield()

    # Verify the form field has the same path
    assert form_field.path == field.path, \
        f"Form field path should be {field.path}, got {form_field.path}"

    print("✓ FilePathField with string path works correctly")


if __name__ == '__main__':
    # Configure Django settings if needed
    if not settings.configured:
        settings.configure(
            DEBUG=True,
            DATABASES={
                'default': {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': ':memory:',
                }
            },
            INSTALLED_APPS=[
                'django.contrib.contenttypes',
                'django.contrib.auth',
            ],
            BASE_DIR=tempfile.gettempdir(),
        )

    # Run tests
    test_filepathfield_with_callable()
    test_filepathfield_with_string()
    print("\n✓ All tests passed!")
