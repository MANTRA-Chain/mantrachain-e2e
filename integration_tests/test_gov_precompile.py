import json
from dataclasses import dataclass

import pytest
from eth_contract.contract import Contract

from .utils import (
    ACCOUNTS,
    DEFAULT_DENOM,
    WEI_PER_DENOM,
    build_contract,
    module_address,
    w3_wait_for_new_blocks_async,
)


@dataclass
class ProposalData:
    id: int
    messages: tuple
    status: int
    finalTallyResult: tuple
    submitTime: int
    depositEndTime: int
    totalDeposit: tuple
    votingStartTime: int
    votingEndTime: int
    metadata: str
    title: str
    summary: str
    proposer: str

    @classmethod
    def from_tuple(cls, t):
        return cls(*t)


PRECOMPILE = Contract(build_contract("IGov")["abi"])
GET_DEPOSIT = PRECOMPILE.fns.getDeposit
GOV = "0x0000000000000000000000000000000000000805"
gas = 400_000


pytestmark = pytest.mark.asyncio


async def test_gov_proposal(mantra):
    w3 = mantra.async_w3
    acct = ACCOUNTS["community"]
    voter = ACCOUNTS["signer1"]
    msg = {
        "@type": "/cosmos.bank.v1beta1.MsgSetSendEnabled",
        "authority": module_address("gov"),
        "send_enabled": [{"denom": DEFAULT_DENOM, "enabled": True}],
    }
    proposal = {
        "title": "test",
        "summary": "test",
        "deposit": f"1{DEFAULT_DENOM}",
        "messages": [msg],
    }
    deposit = [(DEFAULT_DENOM, WEI_PER_DENOM)]
    res = await PRECOMPILE.fns.submitProposal(
        acct.address, json.dumps(proposal).encode(), deposit
    ).transact(w3, acct, to=GOV, gas=gas)
    assert res.status == 1
    pid = int.from_bytes(res.logs[0].data, "big")
    assert pid > 0

    await w3_wait_for_new_blocks_async(w3, 1)
    await PRECOMPILE.fns.deposit(voter.address, pid, deposit).transact(
        w3, voter, to=GOV, gas=gas
    )
    await PRECOMPILE.fns.vote(voter.address, pid, 1, "").transact(
        w3, voter, to=GOV, gas=gas
    )
    weighted_options = [
        (1, "0.5"),  # yes
        (3, "0.3"),  # no
        (2, "0.2"),  # abstain
    ]
    await PRECOMPILE.fns.voteWeighted(
        voter.address, pid, weighted_options, ""
    ).transact(w3, voter, to=GOV, gas=gas)

    await w3_wait_for_new_blocks_async(w3, 1)
    prop = ProposalData.from_tuple(
        await PRECOMPILE.fns.getProposal(pid).call(w3, to=GOV)
    )
    assert prop.id == pid and prop.title == proposal["title"]

    vote = await PRECOMPILE.fns.getVote(pid, voter.address).call(w3, to=GOV)
    assert vote[0] == pid and vote[1].lower() == voter.address.lower()

    proposer_deposit = await GET_DEPOSIT(pid, acct.address).call(w3, to=GOV)
    assert (
        proposer_deposit[0] == pid
        and proposer_deposit[1].lower() == acct.address.lower()
    )

    voter_deposit = await GET_DEPOSIT(pid, voter.address).call(w3, to=GOV)
    assert voter_deposit[0] == pid and voter_deposit[1].lower() == voter.address.lower()

    tally = await PRECOMPILE.fns.getTallyResult(pid).call(w3, to=GOV)
    assert len(tally) >= 4

    res = await PRECOMPILE.fns.cancelProposal(acct.address, pid).transact(
        w3, acct, to=GOV, gas=gas
    )
    assert res.status == 1
    assert res.logs[0].topics[0] == PRECOMPILE.events.CancelProposal.topic
