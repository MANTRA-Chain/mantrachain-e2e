from typing import List, Optional

from pydantic import BaseModel


class Balance(BaseModel):
    amount: str
    denom: str

    def __str__(self):
        return f"{self.amount}{self.denom}"


class GenesisAccount(BaseModel):
    address: str
    coins: List[Balance]


class PeerPacket(BaseModel):
    ip: str
    node_id: str
    peer_id: str
    accounts: List[GenesisAccount]
    gentx: Optional[dict] = None
