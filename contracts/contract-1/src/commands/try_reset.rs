use cosmwasm_std::{DepsMut, Response};

use crate::{state::COUNT, ContractError};

/// Resets the counter to a specified value.
pub fn try_reset(deps: DepsMut, count: u64) -> Result<Response, ContractError> {
    COUNT.save(deps.storage, &count)?;
    Ok(Response::new()
        .add_attribute("action", "reset")
        .add_attribute("new_count", count.to_string()))
}
