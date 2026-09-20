from __future__ import annotations

import pytest

from tests.helpers import WORKSPACE_MODEL
from warden.dsl import TypeSystem, compile_model


@pytest.fixture(scope="session")
def workspace_ts() -> TypeSystem:
    return TypeSystem(compile_model(WORKSPACE_MODEL))
