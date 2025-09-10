use cosmwasm_std::{Deps, StdResult};

use crate::{msg::CountResponse, state::COUNT};

pub fn query_count(deps: Deps) -> StdResult<CountResponse> {
    let count = COUNT.load(deps.storage)?;
    Ok(CountResponse { count })
}
