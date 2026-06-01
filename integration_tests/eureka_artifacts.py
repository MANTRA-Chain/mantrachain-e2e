from __future__ import annotations

import os
from pathlib import Path

import solcx

# Compiler settings match solidity-ibc-eureka/foundry.toml.
_SOLC_VERSION = "0.8.28"
_EVM_VERSION = "cancun"
_OPTIMIZER_RUNS = 10_000

_REMAPPINGS = {
    "forge-std/": "node_modules/forge-std/src/",
    "@openzeppelin-contracts/": "node_modules/@openzeppelin/contracts/",
    "@openzeppelin-upgradeable/": "node_modules/@openzeppelin/contracts-upgradeable/",
    "@sp1-contracts/": "node_modules/sp1-contracts/contracts/src/",
    "@uniswap/permit2/": "node_modules/@uniswap/permit2/",
    # foundry resolves these via the node_modules layout automatically;
    # solc-standalone doesn't, so spell them out.
    "@openzeppelin/contracts/": "node_modules/@openzeppelin/contracts/",
    "@openzeppelin/contracts-upgradeable/": "node_modules/@openzeppelin/contracts-upgradeable/",  # noqa: E501
}


def _find_repo(label: str, env_var: str, rel_candidates, marker) -> Path:
    """First of ``$<env_var>`` then ``rel_candidates`` whose ``marker(path)`` holds;
    raise a ``FileNotFoundError`` listing what was tried otherwise."""
    candidates = []
    if env := os.environ.get(env_var):
        candidates.append(Path(env))
    candidates += rel_candidates
    for c in candidates:
        if marker(c):
            return c
    tried = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"{label} not found; set ${env_var}. Tried:\n  {tried}")


def find_eureka_repo() -> Path:
    here = Path(__file__).resolve().parent.parent
    return _find_repo(
        "solidity-ibc-eureka",
        "EUREKA_REPO_PATH",
        [
            here.parent / "solidity-ibc-eureka",
            here.parent.parent / "solidity-ibc-eureka",
        ],
        lambda c: c.is_dir() and (c / "foundry.toml").is_file(),
    )


def find_pydefi_repo() -> Path:
    here = Path(__file__).resolve().parent.parent
    return _find_repo(
        "pydefi",
        "PYDEFI_REPO_PATH",
        # ``here / "pydefi"`` is a symlink in this repo root.
        [here / "pydefi", here.parent / "pydefi", here.parent.parent / "pydefi"],
        lambda c: c.is_dir() and (c / "pydefi" / "vm").is_dir(),
    )


def _ensure_solc() -> None:
    if _SOLC_VERSION not in {str(v) for v in solcx.get_installed_solc_versions()}:
        solcx.install_solc(_SOLC_VERSION, show_progress=False)


# Compile-once memo, keyed by call-site-natural inputs. Process-scoped.
_COMPILE_CACHE: dict[tuple, dict] = {}


def _compile(
    source_key: str,
    source: str,
    *,
    base_path: Path | None = None,
    remappings: dict[str, str] | None = None,
) -> dict:
    """Run solc-standard with our pinned settings; return the file's contracts dict."""
    _ensure_solc()
    settings: dict = {
        "viaIR": True,
        "evmVersion": _EVM_VERSION,
        "optimizer": {"enabled": True, "runs": _OPTIMIZER_RUNS},
        "metadata": {"bytecodeHash": "none"},
        "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
    }
    if remappings:
        settings["remappings"] = [f"{k}={v}" for k, v in remappings.items()]
    extras: dict = {}
    if base_path is not None:
        extras["base_path"] = str(base_path)
        extras["allow_paths"] = [str(base_path)]
    output = solcx.compile_standard(
        {
            "language": "Solidity",
            "sources": {source_key: {"content": source}},
            "settings": settings,
        },
        solc_version=_SOLC_VERSION,
        **extras,
    )
    errors = [e for e in output.get("errors", []) if e.get("severity") == "error"]
    if errors:
        formatted = "\n".join(e.get("formattedMessage", str(e)) for e in errors)
        raise RuntimeError(f"solc errors compiling {source_key}:\n{formatted}")
    return output["contracts"][source_key]


def _extract(entry: dict) -> dict:
    return {"abi": entry["abi"], "bin": entry["evm"]["bytecode"]["object"]}


def compile_eureka_contract(
    relative_path: str,
    contract_name: str | None = None,
) -> dict:
    """Compile ``relative_path`` (relative to the eureka repo root) and return
    ``{"abi", "bin"}``. ``contract_name`` defaults to the file stem. Cached."""
    repo = find_eureka_repo()
    src = repo / relative_path
    if not src.is_file():
        raise FileNotFoundError(f"{src} not found in {repo}")
    name = contract_name or src.stem
    key = ("eureka", relative_path, name)
    if key not in _COMPILE_CACHE:
        file_out = _compile(
            relative_path, src.read_text(), base_path=repo, remappings=_REMAPPINGS
        )
        if name not in file_out:
            raise KeyError(
                f"contract {name!r} not in {relative_path} "
                f"(found: {', '.join(file_out)})"
            )
        _COMPILE_CACHE[key] = _extract(file_out[name])
    return _COMPILE_CACHE[key]


# Short-name → repo-relative path. Update here if upstream renames a file.
CONTRACTS = {
    # Proxied apps (deployed behind ERC1967Proxy).
    "ICS26Router": "contracts/ICS26Router.sol",
    "ICS20Transfer": "contracts/ICS20Transfer.sol",
    "ICS27GMP": "contracts/ICS27GMP.sol",
    # Beacons used by ICS20Transfer.initialize().
    "Escrow": "contracts/utils/Escrow.sol",
    "IBCERC20": "contracts/utils/IBCERC20.sol",
    # OpenZeppelin pieces from node_modules.
    "AccessManager": "node_modules/@openzeppelin/contracts/access/manager/AccessManager.sol",  # noqa: E501
    "ERC1967Proxy": "node_modules/@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol",  # noqa: E501
    # Test mocks.
    "TestERC20": "test/solidity-ibc/mocks/TestERC20.sol",
    "DummyLightClient": "test/solidity-ibc/mocks/DummyLightClient.sol",
    # Attested-mode light client — for cross-chain tests against the real relayer.
    "AttestationLightClient": "contracts/light-clients/attestation/AttestationLightClient.sol",  # noqa: E501
    # SP1 ICS07-Tendermint light client (zk path, cosmos→EVM).
    "SP1ICS07Tendermint": "contracts/light-clients/sp1-ics07/SP1ICS07Tendermint.sol",  # noqa: E501
    # Real groth16 verifier — v6.1.0 must match the ELFs (sp1-zkvm 6.1); on-file
    # contract is `SP1Verifier` (hence the (path, name) pair). Needs `bun install`.
    "SP1VerifierGroth16": (
        "node_modules/sp1-contracts/contracts/src/v6.1.0/SP1VerifierGroth16.sol",
        "SP1Verifier",
    ),
    "SP1MockVerifier": "node_modules/sp1-contracts/contracts/src/SP1MockVerifier.sol",  # noqa: E501
}


def get_contract(name: str) -> dict:
    """Compile a known Eureka contract by short name. A CONTRACTS value is a path
    (contract = file stem) or a ``(path, contract_name)`` pair."""
    if name not in CONTRACTS:
        raise KeyError(f"unknown Eureka contract {name!r}; known: {sorted(CONTRACTS)}")
    spec = CONTRACTS[name]
    path, contract_name = spec if isinstance(spec, tuple) else (spec, name)
    return compile_eureka_contract(path, contract_name)


# Inline test mocks — local to this repo, not part of solidity-ibc-eureka.

MOCK_V3_POOL_SOL = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IMockToken {
    function mint(address to, uint256 amount) external;
}

/// @notice Trimmed copy of pydefi's MockV3Pool — exact-input 1:1 swap that
/// fires `uniswapV3SwapCallback` so DEXCallbackRouter on DeFiVM pays the pool.
contract MockV3Pool {
    address public immutable token0;
    address public immutable token1;
    uint256 public immutable rateNumerator;
    uint256 public immutable rateDenominator;

    constructor(address _token0, address _token1, uint256 _num, uint256 _den) {
        token0 = _token0;
        token1 = _token1;
        rateNumerator = _num;
        rateDenominator = _den;
    }

    function swap(
        address recipient,
        bool zeroForOne,
        int256 amountSpecified,
        uint160 /*sqrtPriceLimitX96*/,
        bytes calldata data
    ) external returns (int256 amount0, int256 amount1) {
        require(amountSpecified > 0, "MockV3Pool: exact input only");
        uint256 amountIn = uint256(amountSpecified);
        uint256 amountOut = (amountIn * rateNumerator) / rateDenominator;

        address tokenOut = zeroForOne ? token1 : token0;
        IMockToken(tokenOut).mint(recipient, amountOut);

        (bool ok,) = msg.sender.call(
            abi.encodeWithSelector(
                bytes4(0xfa461e33),
                zeroForOne ? int256(amountIn) : -int256(amountOut),
                zeroForOne ? -int256(amountOut) : int256(amountIn),
                data
            )
        );
        require(ok, "MockV3Pool: callback failed");

        amount0 = zeroForOne ? int256(amountIn) : -int256(amountOut);
        amount1 = zeroForOne ? -int256(amountOut) : int256(amountIn);
    }
}
"""


def compile_pydefi_contract(name: str) -> dict:
    """Compile ``pydefi/pydefi/{vm,bridge}/<name>.sol``. Base path is the
    ``pydefi/pydefi/`` root so cross-package imports (``../vm/X.sol`` from a
    bridge composer) resolve. Returns ``{"abi", "bin"}``. Cached."""
    pydefi_dir = find_pydefi_repo() / "pydefi"
    for sub in ("vm", "bridge"):
        src = pydefi_dir / sub / f"{name}.sol"
        if src.is_file():
            break
    else:
        raise FileNotFoundError(f"{name}.sol not found in pydefi/{{vm,bridge}}")
    key = ("pydefi", name)
    if key not in _COMPILE_CACHE:
        file_out = _compile(f"{sub}/{name}.sol", src.read_text(), base_path=pydefi_dir)
        _COMPILE_CACHE[key] = _extract(file_out[name])
    return _COMPILE_CACHE[key]


def compile_inline(source: str, contract_name: str) -> dict:
    """Compile inline Solidity source. Returns ``{"abi", "bin"}``. Cached."""
    key = ("inline", contract_name, source)
    if key not in _COMPILE_CACHE:
        file_out = _compile(f"{contract_name}.sol", source)
        _COMPILE_CACHE[key] = _extract(file_out[contract_name])
    return _COMPILE_CACHE[key]
