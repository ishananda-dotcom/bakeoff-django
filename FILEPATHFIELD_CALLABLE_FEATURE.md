# FilePathField Callable Path Support (FRA-62)

## Overview

FilePathField now supports callable paths for dynamic path resolution. This allows developers to specify paths that are evaluated at runtime, enabling portability across different environments (dev, staging, production).

## Problem Statement

Previously, FilePathField only accepted static string paths. When using `os.path.join()` with settings to construct paths, the migration would capture the resolved path at migration creation time, breaking portability:

```python
# Old approach - path is hardcoded in migration
FilePathField(path=os.path.join(settings.LOCAL_FILE_DIR, 'example_dir'))
# Migration contains: /home/username/server_files/example_dir
```

## Solution

FilePathField now accepts both string and callable paths:

```python
def get_file_path():
    """Dynamic path resolution based on environment."""
    return os.path.join(settings.LOCAL_FILE_DIR, 'example_dir')

# New approach - path is resolved at runtime
FilePathField(path=get_file_path)
```

## Usage Examples

### Basic Usage with Callable

```python
from django.db import models
from django.conf import settings
import os

def get_upload_path():
    """Returns the upload path based on current environment."""
    return os.path.join(settings.BASE_DIR, 'uploads')

class Document(models.Model):
    file = models.FilePathField(
        path=get_upload_path,  # Callable
        allow_files=True,
        allow_folders=False,
    )
```

### Using with Settings

```python
from django.conf import settings

class Config(models.Model):
    config_file = models.FilePathField(
        path=lambda: settings.CONFIG_DIR,
        allow_files=True,
    )
```

### Backward Compatibility

String paths continue to work as before:

```python
class LegacyModel(models.Model):
    file = models.FilePathField(
        path='/static/files',  # String path (still supported)
        allow_files=True,
    )
```

## Implementation Details

### How It Works

1. **Field Definition**: The `path` parameter accepts both strings and callables
2. **Runtime Resolution**: When a form field is created, if `path` is callable, it's invoked to get the actual path
3. **Form Field Generation**: The resolved path is passed to the form field

### Code Changes

The FilePathField.formfield() method handles callable paths:

```python
def formfield(self, **kwargs):
    return super().formfield(
        **{
            "path": self.path() if callable(self.path) else self.path,
            "match": self.match,
            "recursive": self.recursive,
            "form_class": forms.FilePathField,
            "allow_files": self.allow_files,
            "allow_folders": self.allow_folders,
            **kwargs,
        }
    )
```

## Acceptance Criteria

✓ FilePathField.path parameter accepts both string and callable
✓ When callable is provided, it's invoked at runtime to get the actual path
✓ Existing string-based paths continue to work (backward compatibility)
✓ Form field generation works with callable paths
✓ Dynamic path resolution based on environment is supported

## Edge Cases Handled

1. **Callable returning None**: The form field will receive None as the path
2. **Callable raising exceptions**: Exceptions are propagated to the caller
3. **Lambda functions**: Supported as callables
4. **Named functions**: Supported as callables
5. **Callable objects**: Supported (objects with __call__ method)

## Testing

See `test_filepathfield_callable.py` for comprehensive tests covering:
- Callable path resolution
- String path backward compatibility
- Form field generation with both types of paths

## Migration Considerations

When using callable paths in migrations, the callable reference is preserved (not the resolved value), ensuring portability across environments.

## Performance Notes

- Callable paths are only invoked when form fields are created
- No performance impact on model field access
- Minimal overhead for string paths (simple isinstance check)

## Future Enhancements

Potential future improvements:
- Support for callable match patterns
- Support for callable recursive flag
- Caching of resolved paths for performance
