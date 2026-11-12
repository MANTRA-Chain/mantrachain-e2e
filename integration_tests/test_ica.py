import json

import pytest
from pystarport.utils import wait_for_fn

from .ibc_utils import prepare_network
from .test_sanction import GOV, propose
from .utils import DEFAULT_DENOM, assert_transfer, find_log_event_attrs

pytestmark = [pytest.mark.slow, pytest.mark.skipped]

# the first connection hermes opens, which has this id on both chains
CONNECTION = "connection-0"
# Left empty, the SDK fills the register command's --version flag from the
# `version` key of the node's config.toml (the CometBFT version).
VERSION = json.dumps(
    {
        "version": "ics27-1",
        "controller_connection_id": CONNECTION,
        "host_connection_id": CONNECTION,
        "address": "",
        "encoding": "proto3",
        "tx_type": "sdk_multi_msg",
    }
)
# An error ack carries only the ABCI code; 500 is x/sanction's
# ErrAccountBlacklisted.
BLACKLISTED = "ABCI code: 500:"


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    "prepare-network"
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("ica")
    yield from prepare_network(path, "ibc", chain)


def register_ica(host, controller, owner):
    "Open `owner`'s interchain account and return its address on the host."
    rsp = controller.ica_register_account(
        CONNECTION, version=VERSION, from_=owner, gas=400_000
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    # the host's end opens last, after the controller has the address
    wait_for_fn(
        "icahost channel",
        lambda: any(
            c["port_id"] == "icahost" and c["state"] == "STATE_OPEN"
            for c in host.ibc_query_channels(CONNECTION)
        ),
    )
    return controller.ica_query_account(CONNECTION, owner)["address"]


def ica_exec(host, controller, owner, msg):
    "Run `msg` as `owner`'s interchain account and return the host's ack."
    data = controller.ica_generate_packet_data(json.dumps([msg]))
    # timeout_duration maps to a flag ibc-go v10 dropped; the default is 10 min
    rsp = controller.ica_submit_tx(
        CONNECTION, json.dumps(data), timeout_duration=None, from_=owner, gas=400_000
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    sent = find_log_event_attrs(rsp["events"], "send_packet")
    packet = sent["packet_dst_channel"], sent["packet_sequence"]
    query = (
        "write_acknowledgement.packet_dst_channel='{}' "
        "AND write_acknowledgement.packet_sequence='{}'"
    ).format(*packet)

    def written():
        for tx in host.tx_search_rpc(query):
            ack = find_log_event_attrs(
                tx["tx_result"]["events"],
                "write_acknowledgement",
                lambda a: (a["packet_dst_channel"], a["packet_sequence"]) == packet,
            )
            return json.loads(bytes.fromhex(ack["packet_ack_hex"]))

    return wait_for_fn("ica ack", written)


def test_sanctioned_interchain_account(ibc, tmp_path):
    host, controller = ibc.ibc1.cosmos_cli(), ibc.ibc2.cosmos_cli()
    owner = controller.address("community")
    ica = register_ica(host, controller, owner)
    granter = host.create_account("granter")["address"]
    amt = 10**17
    assert_transfer(host, host.address("community"), granter, amt=2 * amt)
    msg_send = "/cosmos.bank.v1beta1.MsgSend"
    rsp = host.grant_authorization(ica, "generic", msg_type=msg_send, from_=granter)
    assert rsp["code"] == 0, rsp["raw_log"]

    def send(sender, recipient):
        return {
            "@type": msg_send,
            "from_address": sender,
            "to_address": recipient,
            "amount": [{"denom": DEFAULT_DENOM, "amount": str(amt)}],
        }

    pull = {
        "@type": "/cosmos.authz.v1beta1.MsgExec",
        "grantee": ica,
        "msgs": [send(granter, ica)],
    }
    balance = host.balance(granter)
    assert "result" in ica_exec(host, controller, owner, pull)
    assert host.balance(granter) == balance - amt
    assert host.balance(ica) == amt

    # messages an interchain account runs skip the ante handler, so the bank
    # send restriction is what stops them
    for sanctioned, msg in [(granter, pull), (ica, send(ica, granter))]:
        fields = {"signer": GOV, "addresses": [sanctioned], "reason": "e2e"}
        propose(ibc.ibc1, tmp_path, "SanctionAddresses", **fields)
        balance = host.balance(sanctioned)
        ack = ica_exec(host, controller, owner, msg)
        assert ack.get("error", "").startswith(BLACKLISTED), ack
        assert host.balance(sanctioned) == balance
