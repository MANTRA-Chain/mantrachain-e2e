from pathlib import Path

import pytest

from .network import connect_custom_mantra, setup_custom_mantra, setup_geth


def pytest_addoption(parser):
    parser.addoption(
        "--chain-config",
        default="mantrachaind",
        action="store",
        metavar="CHAIN_CONFIG",
        required=False,
        help="Specify chain config to test",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "unmarked: fallback mark for unmarked tests")
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "ccv: marks tests as ccv")
    config.addinivalue_line("markers", "asyncio: marks tests as asyncio")
    config.addinivalue_line("markers", "connect: marks connect related tests")
    config.addinivalue_line("markers", "skipped: marks skipped not supported tests")


def pytest_collection_modifyitems(items, config):
    markexpr = config.option.markexpr or ""
    # a mark named in -k or -m opts its tests back in
    selected = f"{config.option.keyword or ''} {markexpr}"
    skip_connect = pytest.mark.skip(reason="Skipping connect tests by default")
    chain_config = config.getoption("chain_config")
    skip_unsupported = pytest.mark.skip(reason=f"not supported for {chain_config}")
    skip_slow_in_asyncio = pytest.mark.skip(reason="slow tests run in the slow group")
    asyncio_only = markexpr.strip() == "asyncio"

    for item in items:
        # When the asyncio matrix is selected, defer slow async tests to the
        # slow group. Stripping the asyncio marker (the previous approach)
        # breaks pytest-asyncio>=1.0, which re-reads it at runtime for loop
        # scoping.
        if asyncio_only and "slow" in item.keywords and "asyncio" in item.keywords:
            item.add_marker(skip_slow_in_asyncio)

        # add "unmarked" marker to tests that have no markers
        if not any(item.iter_markers()):
            item.add_marker("unmarked")

        # skip connect-marked tests unless explicitly requested
        if "connect" in item.keywords and "connect" not in selected:
            item.add_marker(skip_connect)

        if (
            "skipped" in item.keywords
            and chain_config != "mantrachaind"
            and "skipped" not in selected
        ):
            item.add_marker(skip_unsupported)


@pytest.fixture(scope="session", params=[True])
def mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("mantra")
    cfg = Path(__file__).parent / "configs/enable-indexer.jsonnet"
    yield from setup_custom_mantra(path, 26650, cfg, chain=chain)


@pytest.fixture(scope="session", params=[True])
def connect_mantra():
    yield from connect_custom_mantra()


@pytest.fixture(scope="session")
def geth(tmp_path_factory):
    path = tmp_path_factory.mktemp("geth")
    yield from setup_geth(path, 8545)
