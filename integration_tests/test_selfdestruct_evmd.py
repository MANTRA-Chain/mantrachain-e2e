import pytest
from eth_contract.contract import ContractFunction
from eth_contract.utils import get_initcode, send_transaction
from eth_utils import to_checksum_address
from hexbytes import HexBytes

from .network import setup_mantra
from .utils import ACCOUNTS, ADDRS, build_contract, contract_address

pytestmark = pytest.mark.asyncio

VALUE = 1000


@pytest.fixture(scope="module")
def evmd(tmp_path_factory):
    "mantrachaind does not carry the EIP-6780 fix yet"
    path = tmp_path_factory.mktemp("selfdestruct")
    yield from setup_mantra(path, 27600, "evmd")


@pytest.fixture(scope="module", params=["evmd", "geth"])
def cluster(request):
    return request.getfixturevalue(request.param)


async def assert_destructed(w3, address):
    assert await w3.eth.get_balance(address) == 0
    code = await w3.eth.get_code(address)
    assert code == HexBytes("0x"), f"contract code should be deleted, got {code.hex()}"
    assert await w3.eth.get_transaction_count(address) == 0


async def test_selfdestruct(cluster):
    "a contract created and destroyed within the same tx"
    w3 = cluster.async_w3
    deployer = ACCOUNTS["community"]

    artifact = build_contract("Selfdestruct")
    receipt = await send_transaction(w3, deployer, data=get_initcode(artifact))
    exploiter = receipt["contractAddress"]

    # Minimal is created with the exploiter's nonce 1
    address = contract_address(exploiter, 1)
    await send_transaction(w3, deployer, to=address, value=VALUE)

    # Minimal self-destructs to itself, so the balance is burned
    exploit = ContractFunction.from_abi("function exploit()")
    receipt = await exploit().transact(w3, deployer, to=exploiter)
    assert address == to_checksum_address(
        HexBytes(receipt["logs"][0]["topics"][1])[12:]
    )

    await assert_destructed(w3, address)


async def test_selfdestruct_empty_runtime_code(cluster):
    """
    EIP-6780: init code that runs SELFDESTRUCT leaves no runtime code, but the
    account created in this tx is still deleted. See cosmos/evm#1269.
    """
    w3 = cluster.async_w3
    deployer = ACCOUNTS["signer1"]
    beneficiary = ADDRS["signer2"]

    # the transfer below consumes this nonce, so the creation uses `nonce + 1`
    nonce = await w3.eth.get_transaction_count(deployer.address)
    address = contract_address(deployer.address, nonce + 1)

    await send_transaction(w3, deployer, to=address, value=VALUE)
    assert await w3.eth.get_balance(address) == VALUE
    before = await w3.eth.get_balance(beneficiary)

    # PUSH20 <beneficiary>; SELFDESTRUCT - returns no runtime code
    initcode = HexBytes("0x73" + beneficiary[2:] + "ff")
    receipt = await send_transaction(w3, deployer, data=initcode)
    assert receipt["contractAddress"] == address

    assert await w3.eth.get_balance(beneficiary) == before + VALUE
    await assert_destructed(w3, address)
