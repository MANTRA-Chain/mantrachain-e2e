import json
import subprocess
import tempfile

import requests
from pystarport.cosmoscli import CosmosCLI as PystarportCosmosCLI
from pystarport.utils import build_cli_args_safe, interact, parse_amount

from .utils import (
    DEFAULT_DENOM,
    DEFAULT_GAS,
    DEFAULT_GAS_PRICE,
    MNEMONICS,
    get_sync_info,
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


    def sign_tx_json(self, tx, signer, max_priority_price=None, **kwargs):
        if max_priority_price is not None:
            tx["body"]["extension_options"].append(
                {
                    "@type": "/cosmos.evm.ante.v1.ExtensionOptionDynamicFeeTx",
                    "max_priority_price": str(max_priority_price),
                }
            )
        with tempfile.NamedTemporaryFile("w") as fp:
            json.dump(tx, fp)
            fp.flush()
            return self.sign_tx(fp.name, signer, **kwargs)


    def build_evm_tx(self, raw_tx: str, **kwargs):
        default_kwargs = self.get_kwargs()
        return json.loads(
            self.raw(
                "tx",
                "evm",
                "raw",
                raw_tx,
                "-y",
                "--generate-only",
                **(default_kwargs | kwargs),
            )
        )

    def tx_simulate(self, tx, **kwargs):
        default_kwargs = self.get_kwargs()
        return json.loads(
            self.raw(
                "tx",
                "simulate",
                tx,
                **(default_kwargs | kwargs),
            )
        )

    def software_upgrade(self, proposer, proposal, **kwargs):
        default_kwargs = self.get_kwargs()
        rsp = json.loads(
            self.raw(
                "tx",
                "upgrade",
                "software-upgrade",
                proposal["name"],
                "-y",
                "--no-validate",
                from_=proposer,
                # content
                title=proposal.get("title"),
                note=proposal.get("note"),
                upgrade_height=proposal.get("upgrade-height"),
                upgrade_time=proposal.get("upgrade-time"),
                upgrade_info=proposal.get("upgrade-info"),
                summary=proposal.get("summary"),
                deposit=proposal.get("deposit"),
                # basic
                **(default_kwargs | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_base_fee(self, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "feemarket",
                "base-fee",
                **(self.get_base_kwargs() | kwargs),
            )
        )["base_fee"]

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

    def tx_search(self, events: str):
        return json.loads(
            self.raw("q", "txs", query=f'"{events}"', output="json", node=self.node_rpc)
        )

    def tx_search_rpc(self, events: str):
        rsp = requests.get(
            f"{self.node_rpc_http}/tx_search",
            params={
                "query": f'"{events}"',
            },
        ).json()
        assert "error" not in rsp, rsp["error"]
        return rsp["result"]["txs"]

    def query_erc20_token_pair(self, token, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "erc20",
                "token-pair",
                token,
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("token_pair", {})

    def query_erc20_token_pairs(self, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "erc20",
                "token-pairs",
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("token_pairs", [])

    def convert_erc20(self, contract, amt, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "erc20",
                "convert-erc20",
                contract,
                amt,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def register_erc20(self, contract, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "erc20",
                "register-erc20",
                contract,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def rollback(self):
        self.raw("rollback", home=self.data_dir)

    def prune(self, kind="everything"):
        return self.raw("prune", kind, home=self.data_dir).decode()

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

    def fund_community_pool(self, amt, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "distribution",
                "fund-community-pool",
                "-y",
                amt,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def fund_validator_rewards_pool(self, val_addr, amt, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "distribution",
                "fund-validator-rewards-pool",
                "-y",
                val_addr,
                amt,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def set_withdraw_addr(self, addr, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "distribution",
                "set-withdraw-addr",
                "-y",
                addr,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def withdraw_all_rewards(self, generate_only=False, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "distribution",
                "withdraw-all-rewards",
                "-y",
                "--generate-only" if generate_only else None,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def withdraw_rewards(self, val_addr, generate_only=False, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "distribution",
                "withdraw-rewards",
                val_addr,
                "-y",
                "--generate-only" if generate_only else None,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def withdraw_validator_commission(self, val_addr, generate_only=False, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "distribution",
                "withdraw-validator-commission",
                val_addr,
                "-y",
                "--generate-only" if generate_only else None,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def distribution_rewards(self, delegator_addr, **kwargs):
        res = json.loads(
            self.raw(
                "q",
                "distribution",
                "rewards",
                delegator_addr,
                **(self.get_base_kwargs() | kwargs),
            )
        )
        total = res.get("total")
        if not total or total[0] is None:
            return 0
        return parse_amount(total[0])

    def distribution_commission(self, addr, **kwargs):
        res = (
            json.loads(
                self.raw(
                    "q",
                    "distribution",
                    "commission",
                    addr,
                    **(self.get_base_kwargs() | kwargs),
                )
            )
            .get("commission")
            .get("commission")
        )
        if not res or not res[0]:
            return 0
        return parse_amount(res[0])

    def distribution_community_pool(self, **kwargs):
        res = json.loads(
            self.raw(
                "q",
                "distribution",
                "community-pool",
                output="json",
                node=self.node_rpc,
                **kwargs,
            )
        ).get("pool")
        if not res or not res[0]:
            return 0
        return parse_amount(res[0])

    def query_disabled_list(self, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "circuit",
                "disabled-list",
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("disabled_list", [])

    def grant_authorization(self, grantee, authz_type, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "authz",
                "grant",
                grantee,
                authz_type,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def exec_tx_by_grantee(self, tx_file, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "authz",
                "exec",
                tx_file,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def revoke_authorization(self, grantee, msg_type, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "authz",
                "revoke",
                grantee,
                msg_type,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_grants(self, granter, grantee, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "authz",
                "grants",
                granter,
                grantee,
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("grants", [])

    def query_blacklist(self, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "sanction",
                "blacklist",
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("blacklisted_accounts", [])

    def ibc_denom_hash(self, path, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "ibc-transfer",
                "denom-hash",
                path,
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("hash")

    def ibc_transfer(
        self,
        to,
        amount,
        channel,  # src channel
        generate_only=False,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "ibc-transfer",
                "transfer",
                "transfer",
                channel,
                to,
                amount,
                "-y",
                "--generate-only" if generate_only else None,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def export(self, **kwargs):
        raw = self.raw("export", home=self.data_dir, **kwargs)
        if isinstance(raw, bytes):
            raw = raw.decode()
        # skip oracle client log
        idx = raw.find("{")
        if idx == -1:
            raise ValueError("No JSON object found in export output")
        return json.loads(raw[idx:])

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

    def create_periodic_vesting_acct(self, to_address, amount, end_time, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "vesting",
                "create-vesting-account",
                to_address,
                amount,
                end_time,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp["code"] == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def create_periodic_vesting_account(self, to_address, periods, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "vesting",
                "create-periodic-vesting-account",
                to_address,
                periods,
                "-y",
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp["code"] == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp
