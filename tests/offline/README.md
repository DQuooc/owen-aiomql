# Execution core offline tests

Run only this directory with the standard-library runner:

```powershell
python -B -m unittest discover -s tests/offline -p 'test_*.py' -v
```

`-s tests/offline` limits discovery to the fake-SDK tests. `-B` prevents
bytecode files from being written. These tests do not import pytest or its
fixtures. Do not use unrestricted pytest discovery for this suite:
`tests/live/conftest.py` has autouse fixtures that log in to MT5 and clean up
positions with `order_send`.
