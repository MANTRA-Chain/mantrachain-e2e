"""pydefi-specific contract compile + the generic eureka SDK re-exported.

The generic API moved to ``ibc_eureka.contracts.artifacts``; this keeps the pydefi
bits (MockV3Pool, vm/bridge compile) and re-exports it so ``from .eureka_artifacts
import …`` keeps working.
"""

from __future__ import annotations

from pathlib import Path

from ibc_eureka.contracts.artifacts import (
    _COMPILE_CACHE,
    CONTRACTS,
    compile_eureka_contract,
    compile_inline,
    compile_standard,
    extract,
    find_eureka_repo,
    find_repo,
    get_contract,
)

__all__ = [
    "CONTRACTS",
    "MOCK_V3_POOL_SOL",
    "compile_eureka_contract",
    "compile_inline",
    "compile_pydefi_contract",
    "find_eureka_repo",
    "find_pydefi_repo",
    "get_contract",
]


def find_pydefi_repo() -> Path:
    here = Path(__file__).resolve().parent.parent
    return find_repo(
        "pydefi",
        "PYDEFI_REPO_PATH",
        # ``here / "pydefi"`` is a symlink in this repo root.
        [here / "pydefi", here.parent / "pydefi", here.parent.parent / "pydefi"],
        lambda c: c.is_dir() and (c / "pydefi" / "vm").is_dir(),
    )


# Inline test mock — local to this repo, not part of solidity-ibc-eureka.
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
        file_out = compile_standard(
            f"{sub}/{name}.sol", src.read_text(), base_path=pydefi_dir
        )
        _COMPILE_CACHE[key] = extract(file_out[name])
    return _COMPILE_CACHE[key]
