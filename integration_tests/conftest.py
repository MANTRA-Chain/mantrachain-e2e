from contextlib import contextmanager

import pytest

from .network import (
    connect_custom_mantra,
    setup_beacon,
    setup_geth,
    setup_mantra,
    setup_validator,
)


def pytest_configure(config):
    config.addinivalue_line("markers", "unmarked: fallback mark for unmarked tests")
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "connect: marks connect related tests")


def pytest_collection_modifyitems(items, config):
    for item in items:
        if not any(item.iter_markers()):
            item.add_marker("unmarked")


@pytest.fixture(scope="session")
def suspend_capture(pytestconfig):
    """
    used to pause in testing

    Example:
    ```
    def test_simple(suspend_capture):
        with suspend_capture:
            # read user input
            print(input())
    ```
    """

    class SuspendGuard:
        def __init__(self):
            self.capmanager = pytestconfig.pluginmanager.getplugin("capturemanager")

        def __enter__(self):
            self.capmanager.suspend_global_capture(in_=True)

        def __exit__(self, _1, _2, _3):
            self.capmanager.resume_global_capture()

    yield SuspendGuard()


@pytest.fixture(scope="session", params=[True])
def mantra(request, tmp_path_factory):
    path = tmp_path_factory.mktemp("mantra")
    yield from setup_mantra(path, 26650)


@pytest.fixture(scope="session", params=[True])
def connect_mantra():
    yield from connect_custom_mantra()


@contextmanager
def setup_all(path, base_port):
    geth_gen = setup_geth(path, base_port)
    beacon_gen = setup_beacon(path, base_port)
    validator_gen = setup_validator(path, base_port)
    geth_instance = next(geth_gen)
    next(beacon_gen)
    next(validator_gen)

    try:
        yield geth_instance
    finally:
        pass


@pytest.fixture(scope="session")
def geth(tmp_path_factory):
    path = tmp_path_factory.mktemp("geth")
    with setup_all(path, 8545) as geth_instance:
        yield geth_instance
