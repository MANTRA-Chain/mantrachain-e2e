import hashlib

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_hex


def test_ecrecover(mantra):
    w3 = mantra.w3
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

    result = w3.eth.call(
        {
            "to": "0x0000000000000000000000000000000000000001",
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


def test_sha256(mantra):
    w3 = mantra.w3
    test_data = b"hello world"
    result = w3.eth.call(
        {
            "to": "0x0000000000000000000000000000000000000002",
            "data": to_hex(test_data),
        }
    )
    expected = hashlib.sha256(test_data).digest()
    assert result == expected
    print(f"SHA-256 test passed: {result.hex()}")


def test_ripemd160(mantra):
    w3 = mantra.w3
    test_data = b"hello world"
    result = w3.eth.call(
        {
            "to": "0x0000000000000000000000000000000000000003",
            "data": to_hex(test_data),
        }
    )
    # RIPEMD-160 returns 20 bytes, left-padded to 32 bytes
    assert len(result) == 32
    print(f"RIPEMD-160 test passed: {result.hex()}")


def test_identity(mantra):
    w3 = mantra.w3
    test_data = b"hello world test data"
    result = w3.eth.call(
        {
            "to": "0x0000000000000000000000000000000000000004",
            "data": to_hex(test_data),
        }
    )
    assert result == test_data
    print(f"Identity test passed: {result.hex()}")


def test_bigmodexp(mantra):
    w3 = mantra.w3
    # Test 2^2 mod 3 = 1
    base_len = (1).to_bytes(32, "big")  # base length = 1
    exp_len = (1).to_bytes(32, "big")  # exponent length = 1
    mod_len = (1).to_bytes(32, "big")  # modulus length = 1
    base = (2).to_bytes(1, "big")  # base = 2
    exp = (2).to_bytes(1, "big")  # exponent = 2
    mod = (3).to_bytes(1, "big")  # modulus = 3

    input_data = base_len + exp_len + mod_len + base + exp + mod

    result = w3.eth.call(
        {
            "to": "0x0000000000000000000000000000000000000005",
            "data": to_hex(input_data),
        }
    )
    # 2^2 mod 3 = 4 mod 3 = 1
    expected = (1).to_bytes(1, "big")
    assert result == expected
    print(f"BigModExp test passed: {result.hex()}")


def test_bn256add(mantra):
    w3 = mantra.w3
    # Test adding two valid points on the curve
    # Using generator point (1, 2) + point at infinity
    p1_x = (1).to_bytes(32, "big")
    p1_y = (2).to_bytes(32, "big")
    p2_x = (0).to_bytes(32, "big")  # Point at infinity
    p2_y = (0).to_bytes(32, "big")

    input_data = p1_x + p1_y + p2_x + p2_y

    result = w3.eth.call(
        {
            "to": "0x0000000000000000000000000000000000000006",
            "data": to_hex(input_data),
        }
    )
    assert len(result) == 64  # Should return 64 bytes (two 32-byte coordinates)
    print(f"bn256Add test passed: {result.hex()}")


def test_bn256scalarmul(mantra):
    w3 = mantra.w3
    # Multiply generator point by scalar 1
    p_x = (1).to_bytes(32, "big")
    p_y = (2).to_bytes(32, "big")
    scalar = (1).to_bytes(32, "big")

    input_data = p_x + p_y + scalar

    result = w3.eth.call(
        {
            "to": "0x0000000000000000000000000000000000000007",
            "data": to_hex(input_data),
        }
    )
    assert len(result) == 64
    print(f"bn256ScalarMul test passed: {result.hex()}")


def test_bn256pairing(mantra):
    w3 = mantra.w3
    # Empty input should return true (1)
    result = w3.eth.call(
        {"to": "0x0000000000000000000000000000000000000008", "data": "0x"}
    )
    # Empty pairing should return 1 (true)
    expected = (1).to_bytes(32, "big")
    assert result == expected
    print(f"bn256Pairing test passed: {result.hex()}")


def test_blake2f(mantra):
    w3 = mantra.w3
    # Minimal test with 1 round
    rounds = (1).to_bytes(4, "big")
    h = b"\x00" * 64  # 64 bytes of state
    m = b"\x00" * 128  # 128 bytes of message
    t = b"\x00" * 16  # 16 bytes of offset counters
    final_flag = b"\x01"  # 1 byte final flag

    input_data = rounds + h + m + t + final_flag

    result = w3.eth.call(
        {
            "to": "0x0000000000000000000000000000000000000009",
            "data": to_hex(input_data),
        }
    )
    assert len(result) == 64  # Should return 64 bytes
    print(f"BLAKE2F test passed: {result.hex()}")
