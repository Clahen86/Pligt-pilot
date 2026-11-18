"""Fixtures for the Pligt-pilot integration tests."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    import custom_components  # the test package's own folder comes first: add ours to it
    ours = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "custom_components")
    if ours not in custom_components.__path__:
        custom_components.__path__.append(ours)
    yield
