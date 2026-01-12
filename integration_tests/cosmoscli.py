import json
import subprocess

import requests
from pystarport.cosmoscli import CosmosCLI as PystarportCosmosCLI
from pystarport.utils import build_cli_args_safe, interact

from .utils import (
    DEFAULT_DENOM,
    DEFAULT_GAS,
    DEFAULT_GAS_PRICE,
    MNEMONICS,
)


class ChainCommand:
    def __init__(self, cmd):
        self.cmd = cmd

    def __call__(self, cmd, *args, stdin=None, stderr=subprocess.STDOUT, **kwargs):
        "execute mantrachaind"
        args = " ".join(build_cli_args_safe(cmd, *args, **kwargs))
        return interact(f"{self.cmd} {args}", input=stdin, stderr=stderr)


class CosmosCLI(PystarportCosmosCLI):
    "the apis to interact with wallet and blockchain"

    def __init__(
        self,
        data_dir,
        node_rpc,
        cmd,
        chain_id=None,
        gas=DEFAULT_GAS,
        gas_prices=DEFAULT_GAS_PRICE,
    ):
        super().__init__(data_dir, node_rpc, chain_id, cmd, gas, gas_prices)
        self.raw = ChainCommand(cmd)
        genesis_path = self.data_dir / "config" / "genesis.json"
        if genesis_path.exists():
            self._genesis = json.loads(genesis_path.read_text())
            if chain_id is None:
                self.chain_id = self._genesis["chain_id"]
        else:
            self._genesis = {}
            if chain_id is not None:
                # avoid client.yml overwrite flag in textual mode
                self.raw(
                    "config", "set", "client", "chain-id", chain_id, home=self.data_dir
                )
                self.raw(
                    "config", "set", "client", "node", node_rpc, home=self.data_dir
                )

    @property
    def node_rpc_http(self):
        url = self.node_rpc.removeprefix("tcp")
        if not url.startswith(("http://", "https://")):
            url = "http" + url
        return url

    @classmethod
    def init(cls, moniker, data_dir, node_rpc, cmd, chain_id):
        "the node's config is already added"
        ChainCommand(cmd)(
            "init",
            moniker,
            chain_id=chain_id,
            home=data_dir,
        )
        return cls(data_dir, node_rpc, cmd)

    def balance(self, addr, denom=DEFAULT_DENOM, height=0):
        return super().balance(addr, denom=denom, height=height)

    def address(self, name, bech="acc", field="address", skip_create=False):
        try:
            output = self.raw(
                "keys",
                "show",
                name,
                f"--{field}",
                home=self.data_dir,
                keyring_backend="test",
                bech=bech,
            )
        except AssertionError as e:
            if skip_create:
                raise
            if "not a valid name or address" in str(e):
                self.create_account(name, mnemonic=MNEMONICS[name], home=self.data_dir)
                output = self.raw(
                    "keys",
                    "show",
                    name,
                    f"--{field}",
                    home=self.data_dir,
                    keyring_backend="test",
                    bech=bech,
                )
            else:
                raise
        return output.strip().decode()

    def delete_account(self, name):
        return self.raw(
            "keys",
            "delete",
            name,
            "-y",
            "--force",
            home=self.data_dir,
            output="json",
            keyring_backend="test",
        )

    def debug_addr(self, eth_addr, bech="acc"):
        output = self.raw("debug", "addr", eth_addr).decode().strip().split("\n")
        if bech == "val":
            prefix = "Bech32 Val"
        elif bech == "hex":
            prefix = "Address hex:"
        else:
            prefix = "Bech32 Acc"
        for line in output:
            if line.startswith(prefix):
                return line.split()[-1]
        return eth_addr

    def debug_pubkey(self, pubkey):
        output = self.raw("debug", "pubkey", pubkey).decode().strip().split("\n")
        prefix = "Address (EIP-55):"
        for line in output:
            if line.startswith(prefix):
                addr = line.split()[-1]
                return addr[2:] if addr.startswith("0x") else addr
        return pubkey

    def create_tokenfactory_denom(self, subdenom, generate_only=False, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "tokenfactory",
                "create-denom",
                subdenom,
                "--generate-only" if generate_only else None,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_tokenfactory_denoms(self, creator, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "tokenfactory",
                "denoms-from-creator",
                creator,
                **(self.get_base_kwargs() | kwargs),
            )
        )

    def mint_tokenfactory_denom(self, coin, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "tokenfactory",
                "mint",
                coin,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def burn_tokenfactory_denom(self, coin, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "tokenfactory",
                "burn",
                coin,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def tx_search_rpc(self, events: str):
        rsp = requests.get(
            f"{self.node_rpc_http}/tx_search",
            params={
                "query": f'"{events}"',
            },
        ).json()
        assert "error" not in rsp, rsp["error"]
        return rsp["result"]["txs"]

    def set_tokenfactory_denom(self, meta, generate_only=False, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "tokenfactory",
                "set-denom-metadata",
                meta,
                "--generate-only" if generate_only else None,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_denom_authority_metadata(self, denom, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "tokenfactory",
                "denom-authority-metadata",
                denom,
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("authority_metadata")

    def update_tokenfactory_admin(self, denom, address, generate_only=False, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "tokenfactory",
                "change-admin",
                denom,
                address,
                "--generate-only" if generate_only else None,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def set_tokenfactory_before_send_hook(self, denom, address, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "tokenfactory",
                "set-before-send-hook",
                denom,
                address,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_disabled_list(self, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "circuit",
                "disabled-list",
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("disabled_list", [])

    def query_blacklist(self, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "sanction",
                "blacklist",
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("blacklisted_accounts", [])

    def has_module(self, module):
        try:
            self.raw("q", module)
            return True
        except AssertionError:
            return False

    def wasm_store(self, path, wallet, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "wasm",
                "store",
                path,
                "--instantiate-anyof-addresses",
                wallet,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def wasm_instantiate(self, code_id, wallet, label="test", msg="{}", **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "wasm",
                "instantiate",
                code_id,
                msg,
                "--admin",
                wallet,
                "--label",
                label,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def wasm_execute(self, addr, msg, amt=None, **kwargs):
        if isinstance(msg, dict):
            msg = json.dumps(msg)
        cmd = ["tx", "wasm", "execute", addr, msg, "-y"]
        if amt:
            cmd += ["--amount", amt]
        rsp = json.loads(
            self.raw(
                *cmd,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_wasm_contract_state(self, addr, msg, cmd="smart", **kwargs):
        if isinstance(msg, dict):
            msg = json.dumps(msg)
        return json.loads(
            self.raw(
                "q",
                "wasm",
                "contract-state",
                cmd,
                "--b64" if cmd == "raw" else None,
                addr,
                msg,
                **(self.get_base_kwargs() | kwargs),
            )
        )

    def wasm_migrate(self, addr, code_id, msg, **kwargs):
        if isinstance(msg, dict):
            msg = json.dumps(msg)
        rsp = json.loads(
            self.raw(
                "tx",
                "wasm",
                "migrate",
                addr,
                code_id,
                msg,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def total_supply_of(self, denom=DEFAULT_DENOM, **kwargs):
        return super().total_supply_of(denom=denom, **kwargs)

    def provider_create_consumer(self, msg, **kwargs):
        if isinstance(msg, dict):
            msg = json.dumps(msg)
        rsp = json.loads(
            self.raw(
                "tx",
                "provider",
                "create-consumer",
                msg,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def provider_update_consumer(self, msg, **kwargs):
        if isinstance(msg, dict):
            msg = json.dumps(msg)
        rsp = json.loads(
            self.raw(
                "tx",
                "provider",
                "update-consumer",
                msg,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def provider_consumer_genesis(self, consumer_id, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "provider",
                "consumer-genesis",
                consumer_id,
                **(self.get_base_kwargs() | kwargs),
            )
        )

    def provider_opt_in(self, consumer_id, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "provider",
                "opt-in",
                consumer_id,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def oracle_add_currency_pairs(self, pairs, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "oracle",
                "add-currency-pairs",
                "--currency-pairs",
                json.dumps(pairs),
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def oracle_query_currency_pairs(self, **kwargs):
        res = json.loads(
            self.raw(
                "q",
                "oracle",
                "currency-pairs",
                **(self.get_base_kwargs() | kwargs),
            )
        )
        return res.get("currency_pairs", [])

    def cleanup_block_events(self, height):
        return self.raw(
            "cleanup-block-events",
            height,
            home=self.data_dir,
        )

    def query_delegator_starting_info(
        self,
        delegator,
        validator,
        **kwargs,
    ):
        return json.loads(
            self.raw(
                "q",
                "distribution",
                "delegator-starting-info",
                delegator,
                validator,
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("starting_info")

    def query_validator_historical_rewards(
        self,
        delegator,
        period,
        **kwargs,
    ):
        return json.loads(
            self.raw(
                "q",
                "distribution",
                "validator-historical-rewards",
                delegator,
                period,
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("rewards")

    def query_precisebank_fraction(self, addr, **kwargs):
        res = json.loads(
            self.raw(
                "q",
                "precisebank",
                "fractional-balance",
                addr,
                **(self.get_base_kwargs() | kwargs),
            )
        )
        return int(res.get("fractional_balance", {}).get("amount", "0"))

    def query_doc_records(self, **kwargs):
        res = json.loads(
            self.raw(
                "q",
                "document",
                "records",
                **(self.get_base_kwargs() | kwargs),
            )
        )
        return res.get("records", [])

    def query_registry(self, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "document",
                "registry",
                **(self.get_base_kwargs() | kwargs),
            )
        )

    def query_registries(self, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "document",
                "registries",
                **(self.get_base_kwargs() | kwargs),
            )
        )

    def query_provider_info(self, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "ccvconsumer",
                "provider-info",
                **(self.get_base_kwargs() | kwargs),
            )
        )
