import json
import subprocess
import tempfile

import requests
from pystarport.utils import build_cli_args_safe, interact

from .utils import DEFAULT_GAS, DEFAULT_GAS_PRICE, get_sync_info


class ChainCommand:
    def __init__(self, cmd):
        self.cmd = cmd

    def __call__(self, cmd, *args, stdin=None, stderr=subprocess.STDOUT, **kwargs):
        "execute mantrachaind"
        args = " ".join(build_cli_args_safe(cmd, *args, **kwargs))
        return interact(f"{self.cmd} {args}", input=stdin, stderr=stderr)


class CosmosCLI:
    "the apis to interact with wallet and blockchain"

    def __init__(
        self,
        data_dir,
        node_rpc,
        cmd,
        chain_id=None,
    ):
        self.data_dir = data_dir
        genesis_path = self.data_dir / "config" / "genesis.json"
        if genesis_path.exists():
            self._genesis = json.loads(genesis_path.read_text())
            self.chain_id = self._genesis["chain_id"]
        else:
            self._genesis = {}
            self.chain_id = chain_id
        self.node_rpc = node_rpc
        self.raw = ChainCommand(cmd)
        self.output = None
        self.error = None

    @property
    def node_rpc_http(self):
        return "http" + self.node_rpc.removeprefix("tcp")

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

    def validators(self):
        return json.loads(
            self.raw("q", "staking", "validators", output="json", node=self.node_rpc)
        )["validators"]

    def status(self):
        return json.loads(self.raw("status", node=self.node_rpc))

    def block_height(self):
        return int(get_sync_info(self.status())["latest_block_height"])

    def balances(self, addr, height=0, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "bank",
                "balances",
                addr,
                height=height,
                **(self.get_base_kwargs() | kwargs),
            )
        )["balances"]

    def balance(self, addr, denom="uom", height=0):
        denoms = {
            coin["denom"]: int(coin["amount"])
            for coin in self.balances(addr, height=height)
        }
        return denoms.get(denom, 0)

    def address(self, name, bech="acc", field="address"):
        output = self.raw(
            "keys",
            "show",
            name,
            f"--{field}",
            home=self.data_dir,
            keyring_backend="test",
            bech=bech,
        )
        return output.strip().decode()

    def account(self, addr, **kwargs):
        return json.loads(
            self.raw("q", "auth", "account", addr, **(self.get_base_kwargs() | kwargs))
        )

    def transfer(
        self,
        from_,
        to,
        coins,
        generate_only=False,
        event_query_tx=True,
        fees=None,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "bank",
                "send",
                from_,
                to,
                coins,
                "-y",
                "--generate-only" if generate_only else None,
                fees=fees,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def event_query_tx_for(self, hash, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "event-query-tx-for",
                hash,
                **(self.get_base_kwargs() | kwargs),
            )
        )

    def query_all_txs(self, addr, **kwargs):
        txs = self.raw(
            "q",
            "txs-all",
            addr,
            **(self.get_base_kwargs() | kwargs),
        )
        return json.loads(txs)

    def broadcast_tx(self, tx_file, **kwargs):
        kwargs.setdefault("broadcast_mode", "sync")
        kwargs.setdefault("output", "json")
        rsp = json.loads(
            self.raw("tx", "broadcast", tx_file, node=self.node_rpc, **kwargs)
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"], **kwargs)
        return rsp

    def broadcast_tx_json(self, tx, **kwargs):
        with tempfile.NamedTemporaryFile("w") as fp:
            json.dump(tx, fp)
            fp.flush()
            return self.broadcast_tx(fp.name, **kwargs)

    def sign_tx(self, tx_file, signer, **kwargs):
        default_kwargs = self.get_kwargs()
        return json.loads(
            self.raw(
                "tx",
                "sign",
                tx_file,
                from_=signer,
                **(default_kwargs | kwargs),
            )
        )

    def sign_tx_json(self, tx, signer, max_priority_price=None, **kwargs):
        if max_priority_price is not None:
            tx["body"]["extension_options"].append(
                {
                    "@type": "/cosmos.evm.types.v1.ExtensionOptionDynamicFeeTx",
                    "max_priority_price": str(max_priority_price),
                }
            )
        with tempfile.NamedTemporaryFile("w") as fp:
            json.dump(tx, fp)
            fp.flush()
            return self.sign_tx(fp.name, signer, **kwargs)

    def create_account(self, name, mnemonic=None, **kwargs):
        "create new keypair in node's keyring"
        if kwargs.get("coin_type") == 60:
            kwargs["key_type"] = "eth_secp256k1"
        default_kwargs = self.get_kwargs()
        if mnemonic is None:
            output = self.raw(
                "keys",
                "add",
                name,
                **(default_kwargs | kwargs),
            )
        else:
            output = self.raw(
                "keys",
                "add",
                name,
                "--recover",
                stdin=mnemonic.encode() + b"\n",
                **(default_kwargs | kwargs),
            )
        return json.loads(output)

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

    def submit_gov_proposal(self, proposal, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "gov",
                "submit-proposal",
                proposal,
                "-y",
                stderr=subprocess.DEVNULL,
                **(self.get_kwargs_with_gas() | kwargs),
            )
        )
        if rsp.get("code") == 0:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_grant(self, granter, grantee, **kwargs):
        "query grant details by granter and grantee addresses"
        res = json.loads(
            self.raw(
                "q",
                "feegrant",
                "grant",
                granter,
                grantee,
                **(self.get_base_kwargs() | kwargs),
            )
        )
        res = res.get("allowance") or res
        return res

    def query_proposal(self, proposal_id, **kwargs):
        res = json.loads(
            self.raw(
                "q",
                "gov",
                "proposal",
                proposal_id,
                **(self.get_base_kwargs() | kwargs),
            )
        )
        return res.get("proposal") or res

    def staking_pool(self, bonded=True, **kwargs):
        res = self.raw("q", "staking", "pool", **(self.get_base_kwargs() | kwargs))
        res = json.loads(res)
        res = res.get("pool") or res
        return int(res["bonded_tokens" if bonded else "not_bonded_tokens"])

    def query_tally(self, proposal_id, **kwargs):
        res = json.loads(
            self.raw(
                "q",
                "gov",
                "tally",
                proposal_id,
                **(self.get_base_kwargs() | kwargs),
            )
        )
        return res.get("tally") or res

    def gov_vote(self, voter, proposal_id, option, event_query_tx=True, **kwargs):
        default_kwargs = self.get_kwargs()
        rsp = json.loads(
            self.raw(
                "tx",
                "gov",
                "vote",
                proposal_id,
                option,
                "-y",
                from_=voter,
                **(default_kwargs | kwargs),
            )
        )
        if rsp.get("code") == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_bank_send(self, *denoms, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "bank",
                "send-enabled",
                *denoms,
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("send_enabled", [])

    def make_multisig(self, name, signer1, signer2, **kwargs):
        default_kwargs = self.get_kwargs()
        self.raw(
            "keys",
            "add",
            name,
            multisig=f"{signer1},{signer2}",
            multisig_threshold="2",
            **(default_kwargs | kwargs),
        )

    def sign_multisig_tx(self, tx_file, multi_addr, signer_name, **kwargs):
        default_kwargs = self.get_kwargs()
        return json.loads(
            self.raw(
                "tx",
                "sign",
                tx_file,
                from_=signer_name,
                multisig=multi_addr,
                **(default_kwargs | kwargs),
            )
        )

    def combine_multisig_tx(
        self, tx_file, multi_name, signer1_file, signer2_file, **kwargs
    ):
        default_kwargs = self.get_kwargs()
        return json.loads(
            self.raw(
                "tx",
                "multisign",
                tx_file,
                multi_name,
                signer1_file,
                signer2_file,
                **(default_kwargs | kwargs),
            )
        )

    def account_by_num(self, num, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "auth",
                "address-by-acc-num",
                num,
                **(self.get_base_kwargs() | kwargs),
            )
        )

    def get_base_kwargs(self):
        return {
            "home": self.data_dir,
            "node": self.node_rpc,
            "output": "json",
        }

    def get_kwargs(self):
        return self.get_base_kwargs() | {
            "keyring_backend": "test",
            "chain_id": self.chain_id,
        }

    def get_kwargs_with_gas(self):
        return self.get_kwargs() | {
            "gas_prices": DEFAULT_GAS_PRICE,
            "gas": DEFAULT_GAS,
        }

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

    def get_params(self, module, **kwargs):
        default_kwargs = self.get_kwargs()
        return json.loads(self.raw("q", module, "params", **(default_kwargs | kwargs)))

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
                home=self.data_dir,
                **kwargs,
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

    def query_denom_metadata(self, denom, **kwargs):
        return json.loads(
            self.raw(
                "q",
                "bank",
                "denom-metadata",
                denom,
                **(self.get_base_kwargs() | kwargs),
            )
        ).get("metadata")

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

    def set_withdraw_addr(self, bech32_addr, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "distribution",
                "set-withdraw-addr",
                "-y",
                bech32_addr,
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

    def withdraw_rewards(self, val_addr, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "distribution",
                "withdraw-rewards",
                "-y",
                val_addr,
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
        ).get("disabled_list")
