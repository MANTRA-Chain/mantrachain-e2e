use cosmwasm_schema::cw_serde;
use cw_storage_plus::{Item, Map};

pub const COUNT: Item<u64> = Item::new("count");
pub const MAP: Map<u64, MapEntry> = Map::new("map");

#[cw_serde]
pub struct MapEntry {}
