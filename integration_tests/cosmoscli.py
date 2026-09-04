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


def _arg(value):
    "Serialize a dict argument; anything else is passed through untouched."
    return json.dumps(value) if isinstance(value, dict) else value


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

    def _tx(self, *args, **kwargs):
        """Broadcast `tx <args>` and resolve an accepted tx to its result.

        A falsy positional arg is dropped, so optional flags can go inline.
        """
        rsp = json.loads(
            self.raw(
                "tx",
                *(_arg(a) for a in args),
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def _query(self, *args, **kwargs):
        "Run `q <args>` and decode the JSON response."
        return json.loads(
            self.raw(
                "q",
                *(_arg(a) for a in args),
                **(self.get_base_kwargs() | kwargs),
            )
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

    def total_supply_of(self, denom=DEFAULT_DENOM, **kwargs):
        return super().total_supply_of(denom=denom, **kwargs)

    def _show_key(self, name, bech, field):
        return self.raw(
            "keys",
            "show",
            name,
            f"--{field}",
            home=self.data_dir,
            keyring_backend="test",
            bech=bech,
        )

    def address(self, name, bech="acc", field="address", skip_create=False):
        try:
            output = self._show_key(name, bech, field)
        except AssertionError as e:
            if skip_create or "not a valid name or address" not in str(e):
                raise
            self.create_account(name, mnemonic=MNEMONICS[name], home=self.data_dir)
            output = self._show_key(name, bech, field)
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

    def _debug_field(self, subcmd, arg, prefix):
        "Value on the `debug <subcmd>` output line starting with `prefix`, else None."
        for line in self.raw("debug", subcmd, arg).decode().strip().split("\n"):
            if line.startswith(prefix):
                return line.split()[-1]
        return None

    def debug_addr(self, eth_addr, bech="acc"):
        prefix = {"val": "Bech32 Val", "hex": "Address hex:"}.get(bech, "Bech32 Acc")
        return self._debug_field("addr", eth_addr, prefix) or eth_addr

    def debug_pubkey(self, pubkey):
        addr = self._debug_field("pubkey", pubkey, "Address (EIP-55):")
        return addr.removeprefix("0x") if addr else pubkey

    def has_module(self, module):
        try:
            self.raw("q", module)
            return True
        except AssertionError:
            return False

    def tx_search_rpc(self, events: str):
        rsp = requests.get(
            f"{self.node_rpc_http}/tx_search",
            params={
                "query": f'"{events}"',
            },
        ).json()
        assert "error" not in rsp, rsp["error"]
        return rsp["result"]["txs"]

    def cleanup_block_events(self, height):
        return self.raw(
            "cleanup-block-events",
            height,
            home=self.data_dir,
        )

    # --- tokenfactory ---

    def create_tokenfactory_denom(self, subdenom, generate_only=False, **kwargs):
        gen = "--generate-only" if generate_only else None
        return self._tx("tokenfactory", "create-denom", subdenom, gen, **kwargs)

    def mint_tokenfactory_denom(self, coin, **kwargs):
        return self._tx("tokenfactory", "mint", coin, **kwargs)

    def burn_tokenfactory_denom(self, coin, **kwargs):
        return self._tx("tokenfactory", "burn", coin, **kwargs)

    def set_tokenfactory_denom(self, meta, generate_only=False, **kwargs):
        gen = "--generate-only" if generate_only else None
        return self._tx("tokenfactory", "set-denom-metadata", meta, gen, **kwargs)

    def update_tokenfactory_admin(self, denom, address, generate_only=False, **kwargs):
        gen = "--generate-only" if generate_only else None
        return self._tx("tokenfactory", "change-admin", denom, address, gen, **kwargs)

    def set_tokenfactory_before_send_hook(self, denom, address, **kwargs):
        return self._tx(
            "tokenfactory", "set-before-send-hook", denom, address, **kwargs
        )

    def query_tokenfactory_denoms(self, creator, **kwargs):
        return self._query("tokenfactory", "denoms-from-creator", creator, **kwargs)

    def query_denom_authority_metadata(self, denom, **kwargs):
        res = self._query("tokenfactory", "denom-authority-metadata", denom, **kwargs)
        return res.get("authority_metadata")

    # --- wasm ---

    def wasm_store(self, path, wallet, **kwargs):
        return self._tx(
            "wasm",
            "store",
            path,
            "--instantiate-anyof-addresses",
            wallet,
            **kwargs,
        )

    def wasm_instantiate(self, code_id, wallet, label="test", msg="{}", **kwargs):
        return self._tx(
            "wasm",
            "instantiate",
            code_id,
            msg,
            "--admin",
            wallet,
            "--label",
            label,
            **kwargs,
        )

    def wasm_execute(self, addr, msg, amt=None, **kwargs):
        # a None kwarg is dropped by the CLI arg builder, so no branch is needed
        return self._tx("wasm", "execute", addr, msg, amount=amt, **kwargs)

    def wasm_migrate(self, addr, code_id, msg, **kwargs):
        return self._tx("wasm", "migrate", addr, code_id, msg, **kwargs)

    def query_wasm_contract_state(self, addr, msg, cmd="smart", **kwargs):
        b64 = "--b64" if cmd == "raw" else None
        return self._query("wasm", "contract-state", cmd, b64, addr, msg, **kwargs)

    # --- interchain security provider / consumer ---

    def provider_create_consumer(self, msg, **kwargs):
        return self._tx("provider", "create-consumer", msg, **kwargs)

    def provider_update_consumer(self, msg, **kwargs):
        return self._tx("provider", "update-consumer", msg, **kwargs)

    def provider_opt_in(self, consumer_id, **kwargs):
        return self._tx("provider", "opt-in", consumer_id, **kwargs)

    def provider_consumer_genesis(self, consumer_id, **kwargs):
        return self._query("provider", "consumer-genesis", consumer_id, **kwargs)

    def query_provider_info(self, **kwargs):
        return self._query("ccvconsumer", "provider-info", **kwargs)

    # --- oracle ---

    def oracle_add_currency_pairs(self, pairs, **kwargs):
        return self._tx(
            "oracle",
            "add-currency-pairs",
            "--currency-pairs",
            json.dumps(pairs),
            **kwargs,
        )

    def oracle_query_currency_pairs(self, **kwargs):
        return self._query("oracle", "currency-pairs", **kwargs).get(
            "currency_pairs", []
        )

    # --- distribution / precisebank ---

    def query_delegator_starting_info(self, delegator, validator, **kwargs):
        return self._query(
            "distribution",
            "delegator-starting-info",
            delegator,
            validator,
            **kwargs,
        ).get("starting_info")

    def query_validator_historical_rewards(self, delegator, period, **kwargs):
        return self._query(
            "distribution",
            "validator-historical-rewards",
            delegator,
            period,
            **kwargs,
        ).get("rewards")

    def query_precisebank_fraction(self, addr, **kwargs):
        res = self._query("precisebank", "fractional-balance", addr, **kwargs)
        return int(res.get("fractional_balance", {}).get("amount", "0"))

    # --- circuit / sanction / document ---

    def query_disabled_list(self, **kwargs):
        return self._query("circuit", "disabled-list", **kwargs).get(
            "disabled_list", []
        )

    def query_blacklist(self, **kwargs):
        return self._query("sanction", "blacklist", **kwargs).get(
            "blacklisted_accounts", []
        )

    def query_doc_records(self, **kwargs):
        return self._query("document", "records", **kwargs).get("records", [])

    def query_registry(self, **kwargs):
        return self._query("document", "registry", **kwargs)

    def query_registries(self, **kwargs):
        return self._query("document", "registries", **kwargs)
