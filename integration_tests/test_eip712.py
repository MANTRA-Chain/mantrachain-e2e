import base64
import json
import time

import pytest
from eth_account import Account

from .cosmostx_utils import (
    DIRECT,
    AuthInfo,
    Fee,
    LegacyAminoPubKey,
    MultiSignature,
    ProtoAny,
    Timestamp,
    TxBody,
    TxRaw,
    create_multisig_auth_info,
)
from .eip712_utils import (
    create_message_send,
    create_tx_raw_eip712,
    encode_eip712_for_signing,
    eth_pubkey_any,
    signature_to_web3_extension,
)
from .utils import CHAIN_ID, DEFAULT_DENOM, KEYS

GAS = 200000
FEE = {
    "amount": str(GAS * 100000000000),  # default base fee
    "denom": DEFAULT_DENOM,
    "gas": str(GAS),
}
SIGNER = "community"


def _pubkey(cli, name):
    return json.loads(cli.address(name, "acc", "pubkey"))["key"]


def _sender(cli, account, signer):
    addr = cli.address(account)
    acc = cli.account(addr)["account"]["value"]
    return {
        "accountAddress": addr,
        "sequence": int(acc.get("sequence", 0)),
        "accountNumber": int(acc["account_number"]),
        "pubkey": _pubkey(cli, signer),
    }


def _setup(mantra):
    cli = mantra.cosmos_cli()
    chain = {"chainId": mantra.w3.eth.chain_id, "cosmosChainId": CHAIN_ID}
    return cli, chain, _sender(cli, SIGNER, SIGNER)


def _sign(cli, chain, sender, signer=SIGNER, **kwargs):
    "Sign a MsgSend of 1 to signer1, returning the tx parts and the signature."
    params = {
        "destinationAddress": cli.address("signer1"),
        "amount": "1",
        "denom": DEFAULT_DENOM,
    }
    tx = create_message_send(chain, sender, FEE, "", params, **kwargs)
    msg_hash = encode_eip712_for_signing(tx["eipToSign"])
    return tx, Account.unsafe_sign_hash(msg_hash, KEYS[signer]).signature


def _signed_tx(tx, sig, body_fields={}, fee_fields={}):
    "A TxRaw of `tx`; appending to an encoded message sets the fields, unsigned."
    auth_info = AuthInfo(
        signer_infos=tx["authInfo"].signer_infos,
        fee=tx["authInfo"].fee + Fee(**fee_fields).SerializeToString(),
    )
    return TxRaw(
        body_bytes=tx["body"].SerializeToString()
        + TxBody(**body_fields).SerializeToString(),
        auth_info_bytes=auth_info.SerializeToString(),
        signatures=[sig],
    )


def _to_json(cli, signed_tx):
    "The cli only reads txs as JSON."
    b64 = base64.b64encode(signed_tx.SerializeToString()).decode()
    return cli.raw("tx", "decode", b64)


def _broadcast(cli, signed_tx):
    return cli.broadcast_tx_json(json.loads(_to_json(cli, signed_tx)))


def _assert_lands(cli, signed_tx):
    rsp = _broadcast(cli, signed_tx)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert rsp["gas_wanted"] == str(GAS)


class TestValidSignature:
    def test_without_extension(self, mantra):
        cli, chain, sender = _setup(mantra)
        tx, sig = _sign(cli, chain, sender)
        _assert_lands(cli, _signed_tx(tx, sig))

    @pytest.mark.skip(reason="wait enable in ante handler")
    def test_native_tx(self, mantra):
        cli, chain, sender = _setup(mantra)
        tx, sig = _sign(cli, chain, sender)
        extension = signature_to_web3_extension(chain, sender, sig)
        _assert_lands(cli, create_tx_raw_eip712(tx["body"], tx["authInfo"], extension))

    def test_multisig(self, mantra):
        cli, chain, _ = _setup(mantra)
        signers = [SIGNER, "signer1"]
        name = "test_multisig_eip712"
        cli.make_multisig(name, *signers)
        rsp = cli.transfer(
            cli.address(SIGNER), cli.address(name), f"{10**18}{DEFAULT_DENOM}"
        )
        assert rsp["code"] == 0, rsp["raw_log"]

        sender = _sender(cli, name, SIGNER)
        (tx, *_), sigs = zip(*(_sign(cli, chain, sender, s) for s in signers))
        pubkey = LegacyAminoPubKey(
            threshold=len(signers),
            public_keys=[
                eth_pubkey_any(_pubkey(cli, s)).SerializeToString() for s in signers
            ],
        )
        auth_info = create_multisig_auth_info(
            multisig_pubkey_any=ProtoAny(
                type_url="/cosmos.crypto.multisig.LegacyAminoPubKey",
                value=pubkey.SerializeToString(),
            ),
            sequence=sender["sequence"],
            fee_amount=FEE["amount"],
            fee_denom=FEE["denom"],
            gas_limit=FEE["gas"],
            num_signers=len(signers),
        )
        _assert_lands(
            cli,
            TxRaw(
                body_bytes=tx["body"].SerializeToString(),
                auth_info_bytes=auth_info.SerializeToString(),
                signatures=[MultiSignature(signatures=sigs).SerializeToString()],
            ),
        )


class TestUnsignedField:
    """Fields added to a signed tx are rejected (GHSA-7xxp-gq2c-x47x).

    Only SIGN_MODE_DIRECT reaches the bug: its typed data omits them, so pre-fix the
    signature still matched. Under amino they break the signature either way.
    """

    # parametrize counts as a marker, so conftest doesn't add this one
    @pytest.mark.unmarked
    @pytest.mark.parametrize("field", ["granter", "payer", "timeout"])
    def test_rejected_by_ante(self, mantra, field):
        cli, chain, sender = _setup(mantra)
        addr = sender["accountAddress"]
        body_fields, fee_fields = {}, {}
        if field == "granter":
            fee_fields["granter"] = cli.address("signer1")
            # DeductFeeDecorator runs before sig verification and needs a live grant
            rsp = cli.grant_fee_allowance(fee_fields["granter"], addr)
            assert rsp["code"] == 0, rsp["raw_log"]
        elif field == "payer":
            # the sender itself, so the tx needs no second signature
            fee_fields["payer"] = addr
        else:
            body_fields["timeout_timestamp"] = Timestamp(seconds=int(time.time()) + 300)

        tx, sig = _sign(cli, chain, sender, sign_mode=DIRECT)
        rsp = _broadcast(cli, _signed_tx(tx, sig, body_fields, fee_fields))
        # ethsecp256k1 reports the decoder's "unsupported fields" as a bad signature
        assert "signature verification failed" in rsp["raw_log"], rsp
        # rejected in CheckTx, so the same signature still lands without the field
        _assert_lands(cli, _signed_tx(tx, sig))

    def test_unordered_rejected_by_decoder(self, mantra, tmp_path):
        "The ante refuses unordered txs first; `validate-signatures` skips the ante."
        cli, chain, sender = _setup(mantra)
        # the cli's temp app builds the typed data with evm chain id 0, not the chain's
        chain["chainId"] = 0
        tx, sig = _sign(cli, chain, sender, sign_mode=DIRECT)
        tampered = _signed_tx(
            tx,
            sig,
            {
                "unordered": True,
                "timeout_timestamp": Timestamp(seconds=int(time.time()) + 300),
            },
        )

        rsp = _broadcast(cli, tampered)
        assert "unordered transactions are not enabled" in rsp["raw_log"], rsp

        def validate(signed_tx):
            tx_file = tmp_path / "tx.json"
            tx_file.write_bytes(_to_json(cli, signed_tx))
            cli.raw(
                "tx",
                "validate-signatures",
                tx_file,
                home=cli.data_dir,
                node=cli.node_rpc,
                chain_id=cli.chain_id,
            )

        validate(_signed_tx(tx, sig))
        with pytest.raises(Exception, match="signatures validation failed"):
            validate(tampered)
