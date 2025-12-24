import hashlib

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    Prehashed,
    decode_dss_signature,
)
from eth_abi import decode, encode
from eth_utils import to_hex
from web3.exceptions import ContractLogicError

from utils import ADDRESS_PREFIX, ADDRS, eth_to_bech32

pytestmark = pytest.mark.asyncio

PRECOMPILE_P256 = "0x0000000000000000000000000000000000000100"
PRECOMPILE_BECH32 = "0x0000000000000000000000000000000000000400"


def generate_p256_signature_components(message: bytes):
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key = private_key.public_key()
    digest = hashlib.sha256(message).digest()
    signature = private_key.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256())))
    r, s = decode_dss_signature(signature)
    public_numbers = public_key.public_numbers()
    return (
        digest.hex(),
        format(r, "064x"),
        format(s, "064x"),
        format(public_numbers.x, "064x"),
        format(public_numbers.y, "064x"),
    )


async def test_p256_valid(mantra):
    w3 = mantra.async_w3
    msg = b"hello world"
    hash_hex, r_hex, s_hex, x_hex, y_hex = generate_p256_signature_components(msg)
    input_data = bytes.fromhex(hash_hex + r_hex + s_hex + x_hex + y_hex)
    result = await w3.eth.call({"to": PRECOMPILE_P256, "data": to_hex(input_data)})
    assert int.from_bytes(result, "big") == 1


async def test_p256_invalid_lengths(mantra):
    w3 = mantra.async_w3
    for length in [0, 32, 64, 96, 128, 159, 161, 192]:
        result = await w3.eth.call(
            {"to": PRECOMPILE_P256, "data": to_hex(b"\x00" * length)}
        )
        assert result == b""


async def test_p256_boundaries(mantra):
    w3 = mantra.async_w3
    # all zeros and all 0xff bytes
    for data in (bytes(160), b"\xff" * 160):
        result = await w3.eth.call({"to": PRECOMPILE_P256, "data": to_hex(data)})
        assert result == b""


async def test_p256_wrong_components(mantra):
    w3 = mantra.async_w3
    # wrong hash + wrong r, s, x, y components
    invalid_input = b"".join(
        [b"\xb9" * 32, b"\x11" * 32, b"\x22" * 32, b"\x33" * 32, b"\x44" * 32]
    )
    result = await w3.eth.call({"to": PRECOMPILE_P256, "data": to_hex(invalid_input)})
    assert result == b""


async def test_bech32_roundtrip(mantra):
    w3 = mantra.async_w3
    community = ADDRS["community"]
    # hex -> bech32
    method1 = w3.keccak(text="hexToBech32(address,string)")[:4]
    data1 = method1 + encode(["address", "string"], [community, ADDRESS_PREFIX])
    bech32 = decode(
        ["string"], await w3.eth.call({"to": PRECOMPILE_BECH32, "data": to_hex(data1)})
    )[0]
    assert bech32 == eth_to_bech32(community)
    # bech32 -> hex
    method2 = w3.keccak(text="bech32ToHex(string)")[:4]
    data2 = method2 + encode(["string"], [bech32])
    decoded = decode(
        ["address"], await w3.eth.call({"to": PRECOMPILE_BECH32, "data": to_hex(data2)})
    )[0]
    assert decoded.lower() == community.lower()


async def test_bech32_invalid(mantra):
    w3 = mantra.async_w3
    for data in [
        b"",
        b"\x00",
        b"\x00" * 2,
        b"\x00" * 3,
    ]:
        with pytest.raises(ContractLogicError):
            await w3.eth.call({"to": PRECOMPILE_BECH32, "data": to_hex(data)})
