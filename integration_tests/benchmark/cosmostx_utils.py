from typing import Optional

from cprotobuf import Field, ProtoEntity


class Coin(ProtoEntity):
    denom = Field("string", 1)
    amount = Field("string", 2)


class AuthInfo(ProtoEntity):
    signer_infos = Field("bytes", 1, repeated=True)
    fee = Field("bytes", 2)
    tip = Field("bytes", 3)


class Fee(ProtoEntity):
    amount = Field(Coin, 1, repeated=True)
    gas_limit = Field("uint64", 2)
    payer = Field("string", 3)
    granter = Field("string", 4)


class TxBody(ProtoEntity):
    messages = Field("bytes", 1, repeated=True)
    memo = Field("string", 2)
    timeout_height = Field("uint64", 3)
    extension_options = Field("bytes", 1023, repeated=True)
    non_critical_extension_options = Field("bytes", 2047, repeated=True)


class TxRaw(ProtoEntity):
    body_bytes = Field("bytes", 1)
    auth_info_bytes = Field("bytes", 2)
    signatures = Field("bytes", 3, repeated=True)


class ProtoAny(ProtoEntity):
    type_url = Field("string", 1)
    value = Field("bytes", 2)


class Tip(ProtoEntity):
    amount = Field(Coin, 1, repeated=True)
    tipper = Field("string", 2)


class MsgEthereumTx(ProtoEntity):
    MSG_URL = "/cosmos.evm.vm.v1.MsgEthereumTx"
    data = Field(ProtoAny, 1)
    deprecated_hash = Field("string", 3)
    from_ = Field("bytes", 5)
    raw = Field("bytes", 6)


def build_any(type_url: str, msg: Optional[ProtoEntity] = None) -> ProtoAny:
    value = b""
    if msg is not None:
        value = msg.SerializeToString()
    return ProtoAny(type_url=type_url, value=value)
