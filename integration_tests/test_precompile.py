import hashlib
from typing import Optional

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_hex

pytestmark = pytest.mark.asyncio


# Berlin precompile addresses
PRECOMPILE_ECRECOVER = "0x0000000000000000000000000000000000000001"
PRECOMPILE_SHA256 = "0x0000000000000000000000000000000000000002"
PRECOMPILE_RIPEMD160 = "0x0000000000000000000000000000000000000003"
PRECOMPILE_DATACOPY = "0x0000000000000000000000000000000000000004"
PRECOMPILE_BIGMODEXP = "0x0000000000000000000000000000000000000005"
PRECOMPILE_BN256ADD = "0x0000000000000000000000000000000000000006"
PRECOMPILE_BN256SCALARMUL = "0x0000000000000000000000000000000000000007"
PRECOMPILE_BN256PAIRING = "0x0000000000000000000000000000000000000008"
PRECOMPILE_BLAKE2F = "0x0000000000000000000000000000000000000009"
# Cancun precompile addresses
PRECOMPILE_KZG_POINT_EVALUATION = "0x000000000000000000000000000000000000000A"
# Prague precompile addresses
PRECOMPILE_BLS12381_G1_ADD = "0x000000000000000000000000000000000000000b"
PRECOMPILE_BLS12381_G1_MULTIEXP = "0x000000000000000000000000000000000000000C"
PRECOMPILE_BLS12381_G2_ADD = "0x000000000000000000000000000000000000000d"
PRECOMPILE_BLS12381_G2_MULTIEXP = "0x000000000000000000000000000000000000000E"
PRECOMPILE_BLS12381_PAIRING = "0x000000000000000000000000000000000000000F"
PRECOMPILE_BLS12381_MAP_G1 = "0x0000000000000000000000000000000000000010"
PRECOMPILE_BLS12381_MAP_G2 = "0x0000000000000000000000000000000000000011"


async def test_ecrecover(mantra):
    w3 = mantra.async_w3
    account = Account.create()
    message = b"hello world"
    signable_message = encode_defunct(message)
    signed_message = account.sign_message(signable_message)
    message_hash = signed_message.message_hash
    v = signed_message.v
    r = signed_message.r
    s = signed_message.s
    # Prepare input: hash(32) + v(32) + r(32) + s(32)
    input_data = (
        message_hash
        + v.to_bytes(32, "big")
        + r.to_bytes(32, "big")
        + s.to_bytes(32, "big")
    )
    result = await w3.eth.call(
        {
            "to": PRECOMPILE_ECRECOVER,
            "data": to_hex(input_data),
        }
    )
    # The result should be the address (last 20 bytes, padded to 32)
    recovered_address = "0x" + result[-20:].hex()
    expected_address = account.address.lower()

    print(f"ecrecover result: {result.hex()}")
    print(f"recovered address: {recovered_address}")
    print(f"expected address: {expected_address}")

    assert recovered_address == expected_address
    assert len(result) == 32


async def test_sha256(mantra):
    w3 = mantra.async_w3
    test_data = b"hello world"
    result = await w3.eth.call(
        {
            "to": PRECOMPILE_SHA256,
            "data": to_hex(test_data),
        }
    )
    expected = hashlib.sha256(test_data).digest()
    assert result == expected
    print(f"SHA-256 test passed: {result.hex()}")


async def test_ripemd160(mantra):
    w3 = mantra.async_w3
    test_data = b"hello world"
    result = await w3.eth.call(
        {
            "to": PRECOMPILE_RIPEMD160,
            "data": to_hex(test_data),
        }
    )
    # RIPEMD-160 returns 20 bytes, left-padded to 32 bytes
    assert len(result) == 32
    print(f"RIPEMD-160 test passed: {result.hex()}")


async def test_identity(mantra):
    w3 = mantra.async_w3
    test_data = b"hello world test data"
    result = await w3.eth.call(
        {
            "to": PRECOMPILE_DATACOPY,
            "data": to_hex(test_data),
        }
    )
    assert result == test_data
    print(f"Identity test passed: {result.hex()}")


async def test_bigmodexp(mantra):
    w3 = mantra.async_w3
    # Test 2^2 mod 3 = 1
    base_len = (1).to_bytes(32, "big")  # base length = 1
    exp_len = (1).to_bytes(32, "big")  # exponent length = 1
    mod_len = (1).to_bytes(32, "big")  # modulus length = 1
    base = (2).to_bytes(1, "big")  # base = 2
    exp = (2).to_bytes(1, "big")  # exponent = 2
    mod = (3).to_bytes(1, "big")  # modulus = 3
    input_data = base_len + exp_len + mod_len + base + exp + mod
    result = await w3.eth.call(
        {
            "to": PRECOMPILE_BIGMODEXP,
            "data": to_hex(input_data),
        }
    )
    # 2^2 mod 3 = 4 mod 3 = 1
    expected = (1).to_bytes(1, "big")
    assert result == expected
    print(f"BigModExp test passed: {result.hex()}")


async def test_bn256add(mantra):
    w3 = mantra.async_w3
    # Test adding two valid points on the curve
    # Using generator point (1, 2) + point at infinity
    p1_x = (1).to_bytes(32, "big")
    p1_y = (2).to_bytes(32, "big")
    p2_x = (0).to_bytes(32, "big")  # Point at infinity
    p2_y = (0).to_bytes(32, "big")
    input_data = p1_x + p1_y + p2_x + p2_y
    result = await w3.eth.call(
        {
            "to": PRECOMPILE_BN256ADD,
            "data": to_hex(input_data),
        }
    )
    assert len(result) == 64  # Should return 64 bytes (two 32-byte coordinates)
    print(f"bn256Add test passed: {result.hex()}")


async def test_bn256scalarmul(mantra):
    w3 = mantra.async_w3
    # Multiply generator point by scalar 1
    p_x = (1).to_bytes(32, "big")
    p_y = (2).to_bytes(32, "big")
    scalar = (1).to_bytes(32, "big")
    input_data = p_x + p_y + scalar
    result = await w3.eth.call(
        {
            "to": PRECOMPILE_BN256SCALARMUL,
            "data": to_hex(input_data),
        }
    )
    assert len(result) == 64
    print(f"bn256ScalarMul test passed: {result.hex()}")


async def test_bn256pairing(mantra):
    w3 = mantra.async_w3
    # Empty input should return true (1)
    result = await w3.eth.call({"to": PRECOMPILE_BN256PAIRING, "data": "0x"})
    # Empty pairing should return 1 (true)
    expected = (1).to_bytes(32, "big")
    assert result == expected
    print(f"bn256Pairing test passed: {result.hex()}")


async def test_blake2f(mantra):
    w3 = mantra.async_w3
    # Minimal test with 1 round
    rounds = (1).to_bytes(4, "big")
    h = b"\x00" * 64  # 64 bytes of state
    m = b"\x00" * 128  # 128 bytes of message
    t = b"\x00" * 16  # 16 bytes of offset counters
    final_flag = b"\x01"  # 1 byte final flag
    input_data = rounds + h + m + t + final_flag
    result = await w3.eth.call(
        {
            "to": PRECOMPILE_BLAKE2F,
            "data": to_hex(input_data),
        }
    )
    assert len(result) == 64  # Should return 64 bytes
    print(f"BLAKE2F test passed: {result.hex()}")


async def test_all_berlin_precompiles_exist(mantra):
    w3 = mantra.async_w3
    berlin_precompiles = [
        PRECOMPILE_ECRECOVER,
        PRECOMPILE_SHA256,
        PRECOMPILE_RIPEMD160,
        PRECOMPILE_DATACOPY,
        PRECOMPILE_BIGMODEXP,
        PRECOMPILE_BN256ADD,
        PRECOMPILE_BN256SCALARMUL,
        PRECOMPILE_BN256PAIRING,
        PRECOMPILE_BLAKE2F,
    ]
    for address in berlin_precompiles:
        # Check if precompile exists by getting code (should be empty)
        code = await w3.eth.get_code(address)
        print(f"{address}: code length {len(code)}")
        # Precompiles should have empty code but still be callable
        assert len(code) == 0, f"{address} should have empty code"


async def test_precompile_gas_costs_berlin(mantra):
    w3 = mantra.async_w3
    # Test simple inputs to verify gas costs
    test_cases = [
        (PRECOMPILE_ECRECOVER, "0x" + "00" * 128, 3000),  # ECRecover base cost
        (PRECOMPILE_SHA256, "0x" + "00" * 32, 60),  # SHA256 base cost
        (PRECOMPILE_RIPEMD160, "0x" + "00" * 32, 600),  # RIPEMD160 base cost
        (PRECOMPILE_DATACOPY, "0x" + "00" * 32, 15),  # Identity base cost
        (PRECOMPILE_BN256ADD, "0x" + "00" * 128, 150),  # BN256Add cost
        (PRECOMPILE_BN256SCALARMUL, "0x" + "00" * 96, 6000),  # BN256ScalarMul cost
    ]
    for address, data, expected_min_gas in test_cases:
        gas_estimate = await w3.eth.estimate_gas(
            {
                "to": address,
                "data": data,
            }
        )
        print(
            f"{address}: estimated gas {gas_estimate}, expected min {expected_min_gas}"
        )
        assert gas_estimate >= expected_min_gas, f"Gas estimate too low for {address}"


class Spec:
    # BLS12-381 field modulus
    BLS_MODULUS = 0x73EDA753299D7D483339D80809A1D80553BDA402FFFE5BFEFFFFFFFF00000001
    INF_POINT = b"\xc0" + b"\x00" * 47  # Infinity point in G1 (compressed)

    # CORRECTED Generator point G1 (128 bytes: 64 bytes each for X and Y)
    # BLS12-381 coordinates need to be padded to 64 bytes each for the precompile
    G1_GENERATOR = bytes.fromhex(
        # X coordinate: pad to 64 bytes
        "0000000000000000000000000000000017f1d3a73197d7942695638c4fa9ac0fc3688c4f9774b905a14e3a3f171bac586c55e83ff97a1aeffb3af00adb22c6bb"  # noqa: E501
        # Y coordinate: pad to 64 bytes
        "0000000000000000000000000000000008b3f481e3aaa0f1a09e30ed741d8ae4fcf5e095d5d00af600db18cb2c04b3edd03cc744a2888ae40caa232946c5e7e1"  # noqa: E501
    )

    # 2 * Generator (G + G, point doubling result)
    # This is the correct expected result for generator_plus_generator
    G1_GENERATOR_DOUBLE = bytes.fromhex(
        # 2G X coordinate (64 bytes)
        "000000000000000000000000000000000572cbea904d67468808c8eb50a9450c9721db309128012543902d0ac358a62ae28f75bb8f1c7c42c39a8c5529bf0f4e"  # noqa: E501
        # 2G Y coordinate (64 bytes)
        "00000000000000000000000000000000166a9d8cabc673a322fda673779d8e3822ba3ecb8670e461f73bb9021d5fd76a4c56d9d4cd16bd1bba86881979749d28"  # noqa: E501
    )

    # Identity element (point at infinity) - 128 bytes of zeros
    G1_IDENTITY = b"\x00" * 128

    # Test point 1 - also properly padded to 64 bytes each coordinate
    TEST_POINT_1 = bytes.fromhex(
        # X coordinate: pad to 64 bytes
        "000000000000000000000000000000000572cbea904d67468808c8eb50a9450c9721db309128012543902d0ac358a62ae28f75bb8f1c7c42c39a8c5529bf0f4e"  # noqa: E501
        # Y coordinate: pad to 64 bytes
        "00000000000000000000000000000000166a9d8cabc673a322fda673779d8e3822ba3ecb8670e461f73bb9021d5fd76a4c56d9d4cd16bd1bba86881979749d28"  # noqa: E501
    )


def kzg_to_versioned_hash(kzg_commitment: bytes) -> bytes:
    """Convert KZG commitment to versioned hash."""
    hash_result = hashlib.sha256(kzg_commitment).digest()
    # Add version byte (0x01 for KZG)
    return bytes([0x01]) + hash_result[1:]


async def format_precompile_input(
    versioned_hash: Optional[bytes],
    z: int,
    y: int,
    kzg_commitment: bytes,
    kzg_proof: bytes,
) -> bytes:
    """Format the input for the point evaluation precompile (192 bytes total)."""
    z_bytes = z.to_bytes(32, "big")
    y_bytes = y.to_bytes(32, "big")
    if versioned_hash is None:
        versioned_hash = kzg_to_versioned_hash(kzg_commitment)
    return versioned_hash + z_bytes + y_bytes + kzg_commitment + kzg_proof


async def test_kzg_point_evaluation(mantra):
    w3 = mantra.async_w3
    # Use a valid input (infinity point)
    input = await format_precompile_input(
        versioned_hash=None,
        z=Spec.BLS_MODULUS - 1,
        y=0,
        kzg_commitment=Spec.INF_POINT,
        kzg_proof=Spec.INF_POINT,
    )
    res = await w3.eth.call(
        {
            "to": PRECOMPILE_KZG_POINT_EVALUATION,
            "data": to_hex(input),
            "gas": 150000,
        }
    )
    assert (
        res.hex()
        == "000000000000000000000000000000000000000000000000000000000000100073eda753299d7d483339d80809a1d80553bda402fffe5bfeffffffff00000001"  # noqa: E501
    )


@pytest.mark.parametrize(
    "point_a,point_b,expected",
    [
        # Identity element tests
        (Spec.G1_IDENTITY, Spec.G1_IDENTITY, Spec.G1_IDENTITY),
        (Spec.G1_GENERATOR, Spec.G1_IDENTITY, Spec.G1_GENERATOR),
        (Spec.G1_IDENTITY, Spec.G1_GENERATOR, Spec.G1_GENERATOR),
        # Valid point addition tests
        (Spec.G1_GENERATOR, Spec.G1_GENERATOR, Spec.G1_GENERATOR_DOUBLE),
        (Spec.TEST_POINT_1, Spec.G1_IDENTITY, Spec.TEST_POINT_1),
    ],
    ids=[
        "identity_plus_identity",
        "generator_plus_identity",
        "identity_plus_generator",
        "generator_plus_generator",
        "test_point_plus_identity",
    ],
)
async def test_bls12381_g1_add(mantra, point_a, point_b: bytes, expected):
    # Verify input points are correct length
    if len(point_a) != 128 or len(point_b) != 128:
        raise ValueError("Each G1 point must be exactly 128 bytes")
    input_data = point_a + point_b
    w3 = mantra.async_w3
    res = await w3.eth.call(
        {
            "to": PRECOMPILE_BLS12381_G1_ADD,
            "data": "0x" + input_data.hex(),
            "gas": 30000,
        }
    )
    assert len(res) == 128
    assert expected == res
