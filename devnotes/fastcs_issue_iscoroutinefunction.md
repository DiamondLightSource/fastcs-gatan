# `asyncio.iscoroutinefunction` DeprecationWarning on Python 3.14

## Problem

`src/fastcs/methods/method.py` uses `asyncio.iscoroutinefunction`, which is deprecated in Python 3.14 and will be removed in 3.16:

```python
from asyncio import iscoroutinefunction
...
        if not iscoroutinefunction(fn):
            raise TypeError("Method must be async function")
```

The check runs whenever `@command` or `@scan` decorates a method, so on Python 3.14 the warning fires as soon as a module that defines a controller is imported:

```
DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16; use inspect.iscoroutinefunction() instead
```

Projects that run pytest with `filterwarnings = "error"` (the default in the DLS python-copier-template) fail at test collection on 3.14.

Seen with fastcs 0.14.4 (the latest release) and on `main` at 8df703e.

## Suggested fix

Use `inspect.iscoroutinefunction` instead. `method.py` already imports from `inspect`:

```diff
-from asyncio import iscoroutinefunction
 from collections.abc import Callable, Coroutine
-from inspect import Signature, getdoc, signature
+from inspect import Signature, getdoc, iscoroutinefunction, signature
```

## Workaround

Downstream projects can ignore the warning in `pyproject.toml` until a fixed release is out:

```toml
filterwarnings = [
    "error",
    "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning",
]
```
