use cosmwasm_schema::{cw_serde, QueryResponses};
use cw_ownable::{cw_ownable_execute, cw_ownable_query};

use crate::state::MapEntry;

#[cw_serde]
pub struct InstantiateMsg {
    pub count: Option<u64>,
}

#[cw_ownable_query]
#[cw_serde]
#[derive(QueryResponses)]
pub enum QueryMsg {
    #[returns(CountResponse)]
    GetCount {},
    #[returns(Vec<MapEntry>)]
    IterateOverMap { limit: u64 },
    #[returns(MapEntry)]
    GetEntryFromMap { entry: u64 },
}

#[cw_ownable_execute]
#[cw_serde]
pub enum ExecuteMsg {
    ModifyState {},
    SendFunds { receipient: String },
    CallContract { contract: String, reply: bool },
    DeleteEntryOnMap { key: u64 },
    FillMap { limit: u64 },
}

#[cw_serde]
pub struct CountResponse {
    pub count: u64,
}

#[cw_serde]
pub struct MigrateMsg {}
