use cosmwasm_std::{DepsMut, Response};

use crate::{state::COUNT, ContractError};

/// Increments the counter by 1.
pub fn try_increment(deps: DepsMut) -> Result<Response, ContractError> {
    let mut count = COUNT.load(deps.storage)?;
    count += 1;
    COUNT.save(deps.storage, &count)?;
    Ok(Response::new()
        .add_attribute("action", "increment")
        .add_attribute("new_count", count.to_string()))
}
