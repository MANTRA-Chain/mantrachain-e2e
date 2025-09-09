use crate::commands::{self};
use crate::error::ContractError;
use crate::msg::{ExecuteMsg, InstantiateMsg, MigrateMsg, QueryMsg};

use crate::queries;
use crate::state::{MapEntry, COUNT, MAP};
use cosmwasm_std::{entry_point, to_json_binary, Order, Reply};
use cosmwasm_std::{Binary, Deps, DepsMut, Env, MessageInfo, Response, StdResult};
use cw2::set_contract_version;
use mantra_utils::validate_contract;

const CONTRACT_NAME: &str = "mantra:contract-1";
const CONTRACT_VERSION: &str = env!("CARGO_PKG_VERSION");

#[entry_point]
pub fn instantiate(
    deps: DepsMut,
    _env: Env,
    info: MessageInfo,
    msg: InstantiateMsg,
) -> Result<Response, ContractError> {
    set_contract_version(deps.storage, CONTRACT_NAME, CONTRACT_VERSION)?;
    cw_ownable::initialize_owner(deps.storage, deps.api, Some(info.sender.as_str()))?;

    let initial_count = msg.count.unwrap_or(0);
    COUNT.save(deps.storage, &initial_count)?;

    Ok(Response::default().add_attributes(vec![
        ("action", "instantiate".to_string()),
        ("owner", info.sender.to_string()),
    ]))
}

#[entry_point]
pub fn reply(_deps: DepsMut, _env: Env, msg: Reply) -> Result<Response, ContractError> {
    match msg.id {
        1u64 => Ok(Response::default().add_attribute("reply", "ok")),
        _ => panic!("reply id not matched"),
    }
}

#[entry_point]
pub fn execute(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
    msg: ExecuteMsg,
) -> Result<Response, ContractError> {
    match msg {
        ExecuteMsg::UpdateOwnership(action) => {
            cw_utils::nonpayable(&info)?;
            mantra_utils::ownership::update_ownership(deps, env, info, action).map_err(Into::into)
        }
        ExecuteMsg::ModifyState {} => commands::try_increment(deps),
        ExecuteMsg::SendFunds { receipient } => commands::send_funds(deps, env, info, receipient),
        ExecuteMsg::CallContract { contract, reply } => {
            commands::call_contract(env, info, contract, reply)
        }
        ExecuteMsg::DeleteEntryOnMap { key } => commands::delete_entry_on_map(deps, key),
        ExecuteMsg::FillMap { limit } => commands::fill_map(deps, limit),
    }
}

#[entry_point]
pub fn query(deps: Deps, _env: Env, msg: QueryMsg) -> StdResult<Binary> {
    match msg {
        QueryMsg::Ownership {} => Ok(to_json_binary(&cw_ownable::get_ownership(deps.storage)?)?),
        QueryMsg::GetCount {} => Ok(to_json_binary(&queries::query_count(deps)?)?),
        QueryMsg::IterateOverMap { limit } => {
            let entries = MAP
                .range(deps.storage, None, None, Order::Ascending)
                .take(limit as usize)
                .map(|item| {
                    let (_, entry) = item?;
                    Ok(entry)
                })
                .collect::<StdResult<Vec<MapEntry>>>()?;

            Ok(to_json_binary(&entries)?)
        }
        QueryMsg::GetEntryFromMap { entry } => {
            let entry = MAP.load(deps.storage, entry)?;
            Ok(to_json_binary(&entry)?)
        }
    }
}

#[entry_point]
pub fn migrate(deps: DepsMut, _env: Env, _msg: MigrateMsg) -> Result<Response, ContractError> {
    set_contract_version(deps.storage, CONTRACT_NAME, CONTRACT_VERSION)?;
    Ok(Response::default())
}
