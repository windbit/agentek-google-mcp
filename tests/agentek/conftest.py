import pytest

from agentek import errors


@pytest.fixture(autouse=True)
def upstream_error_texts():
    # install() turns Agentek error texts on globally; upstream tests expect their own.
    yield
    errors._enabled = False
