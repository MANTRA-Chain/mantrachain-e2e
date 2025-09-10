mod try_increment;
mod try_reset;

use cosmwasm_std::{
    to_json_binary, BankMsg, CosmosMsg, DepsMut, Empty, Env, MessageInfo, Response, SubMsg, WasmMsg,
};
pub use try_increment::*;
pub use try_reset::*;

use crate::{
    msg::ExecuteMsg,
    state::{MapEntry, MAP},
    ContractError,
};

pub fn send_funds(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
    receipient: String,
) -> Result<Response, ContractError> {
    let coin = cw_utils::one_coin(&info)?;

    let contract_balance = deps
        .querier
        .query_balance(&env.contract.address, &coin.denom)?;
    let recipient_balance = deps.querier.query_balance(&receipient, &coin.denom)?;

    Ok(Response::default()
        .add_attribute(
            "contract balance before action",
            contract_balance.to_string(),
        )
        .add_attribute(
            "recipient balance before action",
            recipient_balance.to_string(),
        )
        .add_message(CosmosMsg::Bank(BankMsg::Send {
            to_address: receipient,
            amount: vec![coin],
        })))
}

pub fn call_contract(
    env: Env,
    info: MessageInfo,
    contract: String,
    reply: bool,
) -> Result<Response, ContractError> {
    let coin = cw_utils::one_coin(&info)?;

    let sub_msg = if reply {
        SubMsg::reply_on_success(
            CosmosMsg::Wasm::<Empty>(WasmMsg::Execute {
                contract_addr: contract,
                msg: to_json_binary(&ExecuteMsg::SendFunds {
                    receipient: env.contract.address.to_string(),
                })?,
                funds: vec![coin],
            }),
            1,
        )
    } else {
        SubMsg::reply_never(CosmosMsg::Wasm::<Empty>(WasmMsg::Execute {
            contract_addr: contract,
            msg: to_json_binary(&ExecuteMsg::SendFunds {
                receipient: env.contract.address.to_string(),
            })?,
            funds: vec![coin],
        }))
    };

    Ok(Response::default().add_submessage(sub_msg))
}

pub fn fill_map(deps: DepsMut, limit: u64) -> Result<Response, ContractError> {
    for i in 0..limit {
        let entry = MapEntry {};
        MAP.save(deps.storage, i, &entry)?;
    }

    Ok(Response::default().add_attribute("action", "fill_map".to_string()))
}

pub fn delete_entry_on_map(deps: DepsMut, key: u64) -> Result<Response, ContractError> {
    MAP.remove(deps.storage, key);

    Ok(Response::default().add_attribute("action", "delete_entry_on_map".to_string()))
}
