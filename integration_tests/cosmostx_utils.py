from typing import Optional

from cprotobuf import Field, ProtoEntity


class PubKey(ProtoEntity):
    key = Field("bytes", 1)


class EPubKey(ProtoEntity):
    key = Field("bytes", 1)


class ExtensionOptionsWeb3Tx(ProtoEntity):
    typed_data_chain_id = Field("uint64", 1)
    fee_payer = Field("string", 2)
    fee_payer_sig = Field("bytes", 3)


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


class ModeInfo(ProtoEntity):
    single = Field("bytes", 1)
    multi = Field("bytes", 2)


class SignDoc(ProtoEntity):
    body_bytes = Field("bytes", 1)
    auth_info_bytes = Field("bytes", 2)
    chain_id = Field("string", 3)
    account_number = Field("uint64", 4)


class SignerInfo(ProtoEntity):
    public_key = Field("bytes", 1)
    mode_info = Field("bytes", 2)
    sequence = Field("uint64", 3)


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


class MsgSend(ProtoEntity):
    from_address = Field("string", 1)
    to_address = Field("string", 2)
    amount = Field(Coin, 3, repeated=True)


class ProtoAny(ProtoEntity):
    type_url = Field("string", 1)
    value = Field("bytes", 2)


class ModeInfoSingle(ProtoEntity):
    mode = Field("int32", 1)


class CompactBitArray(ProtoEntity):
    extra_bits_stored = Field("uint32", 1)
    elems = Field("bytes", 2)


class ModeInfoMulti(ProtoEntity):
    bitarray = Field("bytes", 1)
    mode_infos = Field("bytes", 2, repeated=True)


class MultiSignature(ProtoEntity):
    signatures = Field("bytes", 1, repeated=True)


class LegacyAminoPubKey(ProtoEntity):
    threshold = Field("uint32", 1)
    public_keys = Field("bytes", 2, repeated=True)


class Tip(ProtoEntity):
    amount = Field(Coin, 1, repeated=True)
    tipper = Field("string", 2)


class MsgEthereumTx(ProtoEntity):
    MSG_URL = "/cosmos.evm.vm.v1.MsgEthereumTx"
    data = Field(ProtoAny, 1)
    deprecated_hash = Field("string", 3)
    from_ = Field("bytes", 5)
    raw = Field("bytes", 6)


LEGACY_AMINO = 127
SIGN_DIRECT = 1


def build_any(type_url: str, msg: Optional[ProtoEntity] = None) -> ProtoAny:
    value = b""
    if msg is not None:
        value = msg.SerializeToString()
    return ProtoAny(type_url=type_url, value=value)


def create_compact_bit_array(num_bits, bits_set):
    num_bytes = (num_bits + 7) // 8
    extra_bits = num_bits % 8
    if extra_bits == 0:
        extra_bits = 8

    elems = bytearray(num_bytes)
    for bit_idx in bits_set:
        byte_idx = bit_idx // 8
        bit_pos = 7 - (bit_idx % 8)
        elems[byte_idx] |= 1 << bit_pos

    return CompactBitArray(extra_bits_stored=extra_bits, elems=bytes(elems))


def create_multisig_auth_info(
    multisig_pubkey_any, sequence, fee_amount, fee_denom, gas_limit, num_signers
):
    mode_infos = []
    for _ in range(num_signers):
        single = ModeInfoSingle(mode=LEGACY_AMINO)
        mode_info = ModeInfo(single=single.SerializeToString())
        mode_infos.append(mode_info.SerializeToString())

    bitarray = create_compact_bit_array(num_signers, list(range(num_signers)))
    multi = ModeInfoMulti(bitarray=bitarray.SerializeToString(), mode_infos=mode_infos)
    mode_info = ModeInfo(multi=multi.SerializeToString())
    signer_info = SignerInfo(
        mode_info=mode_info.SerializeToString(),
        sequence=sequence,
        public_key=multisig_pubkey_any.SerializeToString(),
    )
    fee = Fee(
        gas_limit=int(gas_limit),
        amount=[Coin(denom=fee_denom, amount=fee_amount)],
    )
    return AuthInfo(
        signer_infos=[signer_info.SerializeToString()],
        fee=fee.SerializeToString(),
    )
