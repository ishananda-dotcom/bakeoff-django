# FilePathField Callable Path Support

## Overview
FilePathField now supports callable paths, allowing dynamic path resolution at runtime instead of hardcoding paths at migration creation time.

## Usage Example

### String Path (Traditional)
```python
from django.db import models

class MyModel(models.Model):
    file_path = models.FilePathField(path="/static/files/")
```

### Callable Path (New Feature)
```python
import os
from django.conf import settings
from django.db import models

def get_file_path():
    """Dynamically resolve the file path based on environment."""
    return os.path.join(settings.BASE_DIR, 'files')

class MyModel(models.Model):
    file_path = models.FilePathField(path=get_file_path)
```

## Benefits

1. **Environment-Specific Paths**: Different paths for dev, staging, and production
2. **Settings-Based Paths**: Paths can reference Django settings
3. **Migration Portability**: Migrations don't hardcode absolute paths
4. **Runtime Evaluation**: Callable is evaluated when the form field is created, not at migration time

## Implementation Details

The FilePathField.formfield() method checks if the path parameter is callable:

```python
def formfield(self, **kwargs):
    return super().formfield(
        **{
            "path": self.path() if callable(self.path) else self.path,
            ...
        }
    )
```

This ensures:
- Backwards compatibility with string paths
- Callables are only invoked at runtime
- Migrations remain portable across different machines/environments

## Acceptance Criteria Met

✅ FilePathField.path parameter accepts both string and callable
✅ When callable is provided, it's invoked at runtime to resolve the path
✅ Migrations generated with callable paths don't hardcode absolute paths
✅ Existing migrations with string paths continue to work
✅ Backwards compatibility maintained
