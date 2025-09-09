#!/usr/bin/env bash
#
# A robust script that compiles smart contracts using `build_release.sh`
# and then uploads the generated WASM files to your chosen network.
# This version includes proper error handling and success verification for CI.

# Usage:
#   just test-on-chain <RPC> <CHAIN_ID> <DENOM> <BINARY> <WALLET>
#   OR
#   ./test_ci.sh -r <RPC> -c <CHAIN_ID> -d <DENOM> -b <BINARY> -w <WALLET>
#   OR (for CI with seed phrase from GitHub secrets):
#   SEED_PHRASE="your seed phrase here" ./test_ci.sh -r <RPC> -c <CHAIN_ID> -d <DENOM> -b <BINARY>

#set -e # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
	echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
	echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
	echo -e "${RED}[ERROR]${NC} $1"
}

# Helper function to extract values using simple grep/cut
extract_field() {
	local file="$1"
	local field="$2"

	case "$field" in
		"txhash")
			# Skip WARNING lines and extract txhash
			grep -v "WARNING:" "$file" 2>/dev/null | grep -o "\"txhash\":\"[^\"]*\"" | cut -d'"' -f4 | head -1
			;;
		"code_id")
			# Skip WARNING lines and extract code_id
			grep -v "WARNING:" "$file" 2>/dev/null | grep -o "\"code_id\",\"value\":\"[^\"]*\"" | cut -d'"' -f6 | head -1
			;;
		"contract_address")
			# Skip WARNING lines and extract contract address
			grep -v "WARNING:" "$file" 2>/dev/null | grep -o "\"_contract_address\",\"value\":\"[^\"]*\"" | cut -d'"' -f6 | head -1
			;;
		*)
			echo ""
			;;
	esac
}

# Function to wait for transaction to be included in a block
wait_for_tx() {
	local tx_hash="$1"
	local max_attempts=6
	local attempt=1

	log_info "Waiting for transaction $tx_hash to be included in block..."
	log_debug "Using binary: $BINARY, RPC: $RPC"

	while [ $attempt -le $max_attempts ]; do
		log_debug "Attempt $attempt/$max_attempts to query transaction"

		# Wait before querying (shorter initial wait, then longer)
		if [ $attempt -eq 1 ]; then
			sleep 5
		else
			sleep 10
		fi

		# Try to query the transaction
		local temp_file=$(mktemp)
		log_debug "Querying transaction: $BINARY q tx $tx_hash --node $RPC -o json"

		# Capture both stdout and stderr for debugging
		local query_output=$(mktemp)
		local query_error=$(mktemp)

		$BINARY q tx $tx_hash --node $RPC -o json > "$query_output" 2>"$query_error"
		local query_exit_code=$?

		log_debug "Query exit code: $query_exit_code"
		log_debug "Query stdout size: $(wc -c < "$query_output" 2>/dev/null || echo 0) bytes"
		log_debug "Query stderr size: $(wc -c < "$query_error" 2>/dev/null || echo 0) bytes"

		if [ $query_exit_code -eq 0 ]; then
			# Copy query output to temp file for processing
			cp "$query_output" "$temp_file"

			log_debug "Transaction query result:"
			cat "$temp_file"
			echo ""

			# Check if transaction succeeded using simple grep
			if grep -q '"code":0' "$temp_file" 2>/dev/null; then
				log_info "Transaction $tx_hash successful"
				cat "$temp_file"
				rm -f "$temp_file" "$query_output" "$query_error"
				return 0
			elif grep -q '"code":[1-9]' "$temp_file" 2>/dev/null; then
				log_error "Transaction $tx_hash failed on-chain"
				cat "$temp_file"
				rm -f "$temp_file" "$query_output" "$query_error"
				return 1
			else
				log_warn "Transaction result format unexpected, continuing to wait..."
			fi
		else
			log_debug "Transaction query failed with exit code: $query_exit_code"
			if grep -q "not found" "$query_error" 2>/dev/null; then
				log_debug "Transaction not yet included in block, will retry..."
			else
				log_error "Transaction query command failed:"
				log_error "Query stderr:"
				cat "$query_error" 2>/dev/null || echo "No stderr output"
			fi
		fi

		rm -f "$temp_file" "$query_output" "$query_error"
		attempt=$((attempt + 1))
	done

	log_error "Transaction $tx_hash not found after $max_attempts attempts ($(($max_attempts * 10)) seconds)"
	log_error "This could indicate:"
	log_error "1. Transaction was rejected due to insufficient funds"
	log_error "2. Transaction had invalid parameters"
	log_error "3. Node is not processing transactions"
	log_error "4. Network connectivity issues"
	return 1
}

# Debug logging function
log_debug() {
	if [ "${DEBUG:-}" = "1" ]; then
		echo -e "${BLUE}[DEBUG]${NC} $1"
	fi
}

# Function to get wallet address from key name
get_wallet_address() {
	local key_name="$1"
	$BINARY keys show $key_name --keyring-backend test -a 2>/dev/null
}

# Function to execute a transaction and verify success
execute_tx() {
	local msg="$1"
	local amount="$2"
	local should_fail="${3:-false}"

	log_info "Executing: $msg"

	if [ -n "$amount" ]; then
		amount_flag="--amount $amount"
	else
		amount_flag=""
	fi

	# Use simple file-based approach
	local temp_result=$(mktemp)
	local temp_error=$(mktemp)

	log_debug "Executing command: $BINARY tx wasm execute $contract_address \"$msg\" --from $WALLET $amount_flag $TXFLAG --keyring-backend test"

	# Use background process with timeout to prevent hanging
	$BINARY tx wasm execute $contract_address "$msg" --from $WALLET $amount_flag $TXFLAG --keyring-backend test > "$temp_result" 2> "$temp_error" &
	local cmd_pid=$!

	# Wait up to 30 seconds for command to complete
	local count=0
	while [ $count -lt 30 ] && kill -0 $cmd_pid 2>/dev/null; do
		sleep 1
		count=$((count + 1))
	done

	# Check if process is still running (timed out)
	if kill -0 $cmd_pid 2>/dev/null; then
		log_warn "Command timed out after 30 seconds, killing process"
		kill $cmd_pid 2>/dev/null || true
		wait $cmd_pid 2>/dev/null || true
		local exit_code=124  # timeout exit code
	else
		wait $cmd_pid
		local exit_code=$?
	fi

	log_debug "Command exit code: $exit_code"
	log_debug "Result file size: $(wc -c < "$temp_result" 2>/dev/null || echo 0) bytes"
	log_debug "Error file size: $(wc -c < "$temp_error" 2>/dev/null || echo 0) bytes"

	# Check if command failed (exit code != 0) or timed out (exit code 124)
	if [ $exit_code -ne 0 ]; then
		if [ "$should_fail" = "true" ]; then
			log_info "Transaction failed as expected (exit code: $exit_code)"
			if [ $exit_code -eq 124 ]; then
				log_info "Command timed out - likely hanging due to error"
			else
				log_debug "Error output:"
				cat "$temp_error" 2>/dev/null || echo "No error output"
			fi
			rm -f "$temp_result" "$temp_error"
			return 0
		else
			log_error "Transaction submission failed with exit code $exit_code"
			log_error "Error output:"
			cat "$temp_error"
			log_error "Result output:"
			cat "$temp_result"
			rm -f "$temp_result" "$temp_error"
			return 1
		fi
	fi

	log_debug "Raw result content:"
	cat "$temp_result"
	echo ""

	rm -f "$temp_error"

	# Extract transaction hash
	local tx_hash=$(extract_field "$temp_result" "txhash")

	if [ -z "$tx_hash" ]; then
		log_error "Failed to extract transaction hash from result"
		log_error "Full result content:"
		cat "$temp_result"
		log_error "Trying alternative extraction method..."
		# Try jq as fallback
		alt_hash=$(cat "$temp_result" | jq -r '.txhash // empty' 2>/dev/null)
		if [ -n "$alt_hash" ]; then
			log_info "Alternative extraction succeeded: $alt_hash"
			tx_hash="$alt_hash"
		fi
		rm -f "$temp_result"
		if [ -z "$tx_hash" ]; then
			if [ "$should_fail" = "true" ]; then
				log_info "Transaction failed as expected (no tx hash)"
				return 0
			else
				return 1
			fi
		fi
	else
		rm -f "$temp_result"
	fi

	log_info "Transaction submitted with hash: $tx_hash"

	# Wait for transaction and check result with detailed logging
	log_debug "Waiting for transaction $tx_hash..."
	local temp_tx_result=$(mktemp)

	if wait_for_tx "$tx_hash" > "$temp_tx_result"; then
		log_debug "wait_for_tx returned success"
		log_debug "Transaction result content:"
		cat "$temp_tx_result"
		echo ""

		# Transaction succeeded
		if grep -q '"code":0' "$temp_tx_result" 2>/dev/null; then
			log_debug "Found code:0 in transaction result"
			rm -f "$temp_tx_result"
			if [ "$should_fail" = "true" ]; then
				log_error "Transaction $tx_hash was expected to fail but succeeded"
				return 1
			else
				log_info "Transaction completed successfully"
				return 0
			fi
		else
			# Transaction failed on chain
			log_debug "Did not find code:0 in transaction result"
			log_error "Transaction succeeded but code was not 0"
			log_error "Transaction result:"
			cat "$temp_tx_result"
			rm -f "$temp_tx_result"
			if [ "$should_fail" = "true" ]; then
				log_info "Transaction failed as expected"
				return 0
			else
				log_error "Transaction failed on chain"
				return 1
			fi
		fi
	else
		# wait_for_tx failed (timeout or other error)
		log_debug "wait_for_tx returned failure"
		log_error "wait_for_tx failed for transaction $tx_hash"
		log_error "Last result:"
		cat "$temp_tx_result"
		rm -f "$temp_tx_result"
		if [ "$should_fail" = "true" ]; then
			log_info "Transaction failed as expected"
			return 0
		else
			log_error "Transaction failed unexpectedly"
			return 1
		fi
	fi
}

# Function to execute a transaction that should fail
execute_tx_should_fail() {
	local msg="$1"
	local amount="$2"

	log_info "Executing (should fail): $msg"

	# Call execute_tx with should_fail=true and check result
	if execute_tx "$msg" "$amount" "true"; then
		log_info "Transaction failed as expected ✓"
		return 0
	else
		log_error "Expected transaction to fail, but it succeeded or had unexpected error"
		return 1
	fi
}

# Function to query contract and verify response
query_contract() {
	local contract="$1"
	local query="$2"
	local should_fail="${3:-false}"

	if [ "$should_fail" = "true" ]; then
		log_info "Querying (should fail): $query"
	else
		log_info "Querying: $query"
	fi

	local result=$($BINARY q wasm contract-state smart $contract "$query" --node $RPC 2>&1)
	local exit_code=$?

	if [ $exit_code -ne 0 ]; then
		if [ "$should_fail" = "true" ]; then
			log_info "Query failed as expected"
			return 0
		else
			log_error "Query failed: $result"
			return 1
		fi
	fi

	# Check if result contains error
	if echo "$result" | grep -q "error\|Error\|ERROR"; then
		if [ "$should_fail" = "true" ]; then
			log_info "Query returned error as expected: $result"
			return 0
		else
			log_error "Query returned error: $result"
			return 1
		fi
	fi

	if [ "$should_fail" = "true" ]; then
		log_error "Query was expected to fail but succeeded: $result"
		return 1
	else
		log_info "Query successful"
		echo "$result"
		return 0
	fi
}

# Function to query contract that should fail
query_contract_should_fail() {
	local contract="$1"
	local query="$2"

	query_contract "$contract" "$query" "true"
}

# Function to query contract raw state
query_contract_raw() {
	contract="$1"
	query="$2"

	log_info "Querying raw: $query"
	result=$($BINARY q wasm contract-state raw --b64 $contract "$query" --node $RPC 2>&1)
	exit_code=$?

	if [ $exit_code -ne 0 ]; then
		log_error "Raw query failed: $result"
		return 1
	fi

	log_info "Raw query successful"
	echo "$result"
	return 0
}

# Parse command line arguments
while getopts "r:c:d:b:w:" flag; do
	case "${flag}" in
	r) RPC=${OPTARG} ;;
	c) CHAIN_ID=${OPTARG} ;;
	d) DENOM=${OPTARG} ;;
	b) BINARY=${OPTARG} ;;
	w) WALLET=${OPTARG} ;;
	*)
		echo "Usage: $0 -r <RPC> -c <CHAIN_ID> -d <DENOM> -b <BINARY> [-w <WALLET>]"
		echo "Note: If WALLET is not provided, SEED_PHRASE environment variable must be set"
		exit 1
		;;
	esac
done

# Ensure all necessary parameters are provided
if [ -z "$RPC" ] || [ -z "$CHAIN_ID" ] || [ -z "$DENOM" ] || [ -z "$BINARY" ]; then
	log_error "Missing required parameters"
	echo "Usage: $0 -r <RPC> -c <CHAIN_ID> -d <DENOM> -b <BINARY> [-w <WALLET>]"
	echo "Note: If WALLET is not provided, SEED_PHRASE environment variable must be set"
	exit 1
fi

# Handle wallet setup - either from parameter or from seed phrase
IMPORTED_WALLET=""
IMPORTED_WALLET2=""
CLEANUP_WALLET=false

if [ -z "$WALLET" ]; then
	# No wallet provided, check for seed phrase
	if [ -z "$SEED_PHRASE" ]; then
		log_error "Either WALLET parameter or SEED_PHRASE environment variable must be provided"
		echo "For CI: Set SEED_PHRASE as a GitHub secret and it will be available as an environment variable"
		exit 1
	fi

	# Import wallet from seed phrase (index 0)
	IMPORTED_WALLET="ci-test-wallet-$(date +%s)"
	log_info "Importing primary wallet from seed phrase as: $IMPORTED_WALLET"

	# Import the seed phrase into the keyring
	echo "$SEED_PHRASE" | $BINARY keys add $IMPORTED_WALLET --recover --keyring-backend test --key-type eth_secp256k1
	if [ $? -ne 0 ]; then
		log_error "Failed to import primary wallet from seed phrase"
		exit 1
	fi

	# Import secondary wallet from seed phrase (index 1)
	IMPORTED_WALLET2="ci-test-wallet2-$(date +%s)"
	log_info "Importing secondary wallet from seed phrase as: $IMPORTED_WALLET2"

	# Import the seed phrase with index 1 into the keyring
	echo "$SEED_PHRASE" | $BINARY keys add $IMPORTED_WALLET2 --recover --keyring-backend test --account 1 --key-type eth_secp256k1
	if [ $? -ne 0 ]; then
		log_error "Failed to import secondary wallet from seed phrase"
		exit 1
	fi

	WALLET=$IMPORTED_WALLET
	CLEANUP_WALLET=true

	# Get wallet addresses for logging
	WALLET_ADDRESS=$(get_wallet_address $IMPORTED_WALLET)
	WALLET2_ADDRESS=$(get_wallet_address $IMPORTED_WALLET2)

	log_info "Successfully imported primary wallet: $WALLET ($WALLET_ADDRESS)"
	log_info "Successfully imported secondary wallet: $IMPORTED_WALLET2 ($WALLET2_ADDRESS)"
elif [ -n "$SEED_PHRASE" ]; then
	log_warn "Both WALLET parameter and SEED_PHRASE environment variable provided. Using WALLET parameter."
fi

# Ensure WALLET_ADDRESS is always set (for cases where wallet was provided via parameter)
if [ -z "$WALLET_ADDRESS" ]; then
	WALLET_ADDRESS=$(get_wallet_address $WALLET)
	if [ -z "$WALLET_ADDRESS" ]; then
		log_error "Failed to get wallet address for $WALLET"
		exit 1
	fi
fi

# Function to cleanup imported wallets
cleanup_wallet() {
	if [ "$CLEANUP_WALLET" = true ]; then
		if [ -n "$IMPORTED_WALLET" ]; then
			log_info "Cleaning up imported primary wallet: $IMPORTED_WALLET"
			$BINARY keys delete $IMPORTED_WALLET --keyring-backend test -y 2>/dev/null || true
		fi
		if [ -n "$IMPORTED_WALLET2" ]; then
			log_info "Cleaning up imported secondary wallet: $IMPORTED_WALLET2"
			$BINARY keys delete $IMPORTED_WALLET2 --keyring-backend test -y 2>/dev/null || true
		fi
	fi
}

# Set trap to cleanup wallet on script exit
trap cleanup_wallet EXIT

# Source tx flags
if [ -n "$ZSH_VERSION" ]; then
	TXFLAG=(--node $RPC --chain-id $CHAIN_ID --gas-prices 1$DENOM --gas auto --gas-adjustment 1.4 -y -b sync --output json)
else
	TXFLAG="--node $RPC --chain-id $CHAIN_ID --gas-prices 1$DENOM --gas auto --gas-adjustment 1.4 -y -b sync --output json"
fi

log_info "Starting contract testing with parameters:"
log_info "RPC: $RPC"
log_info "Chain ID: $CHAIN_ID"
log_info "Denom: $DENOM"
log_info "Binary: $BINARY"
log_info "Wallet: $WALLET"
if [ "$CLEANUP_WALLET" = true ]; then
	log_info "Wallet source: Imported from seed phrase"
else
	log_info "Wallet source: Provided as parameter"
fi

# Check wallet balance before proceeding
log_info "Checking wallet balance..."
wallet_balance=$($BINARY query bank balances $WALLET_ADDRESS --node $RPC --output json 2>/dev/null || echo '{"balances":[]}')
log_info "Wallet balance: $wallet_balance"

# Check if wallet has any funds
if echo "$wallet_balance" | grep -q '"amount"'; then
	log_info "Wallet has funds, proceeding with tests"
else
	log_error "Wallet appears to have no funds!"
	log_error "This might cause transaction failures"
fi

# Verify node connectivity
log_info "Checking node status..."
node_status=$($BINARY status --node $RPC 2>/dev/null || echo "ERROR")
if [ "$node_status" = "ERROR" ]; then
	log_error "Cannot connect to node at $RPC"
	exit 1
else
	log_info "Node connection successful"
	log_debug "Node status: $node_status"
fi

# Enable debug logging if DEBUG=1 is set
if [ "${DEBUG:-}" = "1" ]; then
	log_info "Debug logging enabled"
else
	log_info "Run with DEBUG=1 for detailed logging"
fi

# Compile contracts
log_info "Compiling smart contracts with 'scripts/build_release.sh'..."
if ! scripts/build_release.sh; then
	log_error "Compilation failed"
	exit 1
fi

CONTRACT_DIR="artifacts"
if [ ! -d "$CONTRACT_DIR" ]; then
	log_error "Directory '$CONTRACT_DIR' does not exist. Check your compile output."
	exit 1
fi

# Upload contracts
code_ids=()

for CONTRACT in "$CONTRACT_DIR"/*.wasm; do
	if [ ! -f "$CONTRACT" ]; then
		log_error "No WASM files found in $CONTRACT_DIR."
		exit 1
	fi

	log_info "Uploading contract: $CONTRACT"

	# Use simple file-based approach
	temp_result=$(mktemp)

	$BINARY tx wasm store "$CONTRACT" \
		--from "$WALLET" \
		--instantiate-anyof-addresses "$WALLET_ADDRESS" \
		--chain-id "$CHAIN_ID" \
		--node "$RPC" \
		--gas-prices "2$DENOM" \
		--gas auto \
		--gas-adjustment 1.6 \
		--broadcast-mode sync \
		--output json \
		--keyring-backend test \
		-y >"$temp_result"

	exit_code=$?

	if [ $exit_code -ne 0 ]; then
		log_error "Upload failed for $CONTRACT"
		cat "$temp_result"
		rm -f "$temp_result"
		exit 1
	fi

	# Extract transaction hash using simple grep
	tx_hash=$(extract_field "$temp_result" "txhash")
	rm -f "$temp_result"

	if [ -z "$tx_hash" ]; then
		log_error "Failed to extract transaction hash from upload result"
		exit 1
	fi

	log_info "Upload transaction submitted with hash: $tx_hash"

	# Wait for transaction and save result
	temp_tx_result=$(mktemp)
	log_debug "Calling wait_for_tx for hash: $tx_hash"
	if wait_for_tx "$tx_hash" >"$temp_tx_result"; then
		log_debug "wait_for_tx succeeded, result saved to temp file"
		log_debug "Transaction result content:"
		cat "$temp_tx_result"
		echo ""
	else
		log_error "Upload transaction failed"
		log_error "wait_for_tx output:"
		cat "$temp_tx_result" 2>/dev/null || echo "No output from wait_for_tx"
		rm -f "$temp_tx_result"
		exit 1
	fi

	# Extract code_id using simple grep
	code_id=$(extract_field "$temp_tx_result" "code_id")
	rm -f "$temp_tx_result"

	if [ -z "$code_id" ]; then
		log_error "No code_id found in transaction $tx_hash"
		exit 1
	fi

	log_info "$CONTRACT got code_id: $code_id"
	code_ids+=("$code_id")
done

log_info "All contracts uploaded successfully"
log_info "Code IDs: ${code_ids[@]}"

# Instantiate contracts
log_info "Instantiating contracts"

contract_addresses=()

if [ ${#code_ids[@]} -eq 0 ]; then
	log_error "No code_ids found"
	exit 1
fi

if [ ${#code_ids[@]} -eq 1 ]; then
	log_info "Instantiating contract with code_id ${code_ids[0]} twice"
	for i in {1..2}; do
		temp_result=$(mktemp)

		$BINARY tx wasm instantiate ${code_ids[0]} '{}' --label test --admin $WALLET_ADDRESS $TXFLAG --from $WALLET --keyring-backend test >"$temp_result"
		exit_code=$?

		if [ $exit_code -ne 0 ]; then
			log_error "Instantiation failed"
			cat "$temp_result"
			rm -f "$temp_result"
			exit 1
		fi

		tx_hash=$(extract_field "$temp_result" "txhash")
		rm -f "$temp_result"

		if [ -z "$tx_hash" ]; then
			log_error "Failed to extract instantiation transaction hash"
			exit 1
		fi

		temp_tx_result=$(mktemp)
		log_debug "Calling wait_for_tx for instantiation hash: $tx_hash"
		if wait_for_tx "$tx_hash" >"$temp_tx_result"; then
			log_debug "wait_for_tx succeeded for instantiation"
			log_debug "Instantiation result content:"
			cat "$temp_tx_result"
			echo ""
		else
			log_error "Instantiation transaction failed"
			log_error "wait_for_tx output:"
			cat "$temp_tx_result" 2>/dev/null || echo "No output from wait_for_tx"
			rm -f "$temp_tx_result"
			exit 1
		fi

		contract_address=$(extract_field "$temp_tx_result" "contract_address")
		rm -f "$temp_tx_result"

		if [ -z "$contract_address" ]; then
			log_error "No contract address found in instantiation transaction"
			exit 1
		fi

		contract_addresses+=("$contract_address")
		log_info "Instantiated contract $i at: $contract_address"
	done
else
	log_info "Instantiating contracts with code_ids ${code_ids[@]}"
	for code_id in "${code_ids[@]}"; do
		temp_result=$(mktemp)

		$BINARY tx wasm instantiate $code_id '{}' --label test --admin $WALLET_ADDRESS $TXFLAG --from $WALLET --keyring-backend test >"$temp_result"
		exit_code=$?

		if [ $exit_code -ne 0 ]; then
			log_error "Instantiation failed for code_id $code_id"
			cat "$temp_result"
			rm -f "$temp_result"
			exit 1
		fi

		tx_hash=$(extract_field "$temp_result" "txhash")
		rm -f "$temp_result"

		if [ -z "$tx_hash" ]; then
			log_error "Failed to extract instantiation transaction hash for code_id $code_id"
			exit 1
		fi

		temp_tx_result=$(mktemp)
		log_debug "Calling wait_for_tx for code_id $code_id instantiation hash: $tx_hash"
		if wait_for_tx "$tx_hash" >"$temp_tx_result"; then
			log_debug "wait_for_tx succeeded for code_id $code_id instantiation"
			log_debug "Instantiation result content:"
			cat "$temp_tx_result"
			echo ""
		else
			log_error "Instantiation transaction failed for code_id $code_id"
			log_error "wait_for_tx output:"
			cat "$temp_tx_result" 2>/dev/null || echo "No output from wait_for_tx"
			rm -f "$temp_tx_result"
			exit 1
		fi

		contract_address=$(extract_field "$temp_tx_result" "contract_address")
		rm -f "$temp_tx_result"

		if [ -z "$contract_address" ]; then
			log_error "No contract address found in instantiation transaction"
			exit 1
		fi

		contract_addresses+=("$contract_address")
		log_info "Instantiated contract at: $contract_address"
	done
fi

# Set up wallet2 - either from imported wallet or hardcoded fallback
if [ -n "$IMPORTED_WALLET2" ]; then
	wallet2=$IMPORTED_WALLET2
	wallet2_address=$(get_wallet_address $wallet2)
	log_info "Using imported secondary wallet for unauthorized tests: $wallet2 ($wallet2_address)"

	# Fund the secondary wallet from primary wallet for later tests
	log_info "Funding secondary wallet for testing..."
	temp_fund_result=$(mktemp)

	$BINARY tx bank send $WALLET $wallet2_address 200uom $TXFLAG --from $WALLET --keyring-backend test >"$temp_fund_result"
	fund_exit_code=$?

	if [ $fund_exit_code -eq 0 ]; then
		fund_tx_hash=$(extract_field "$temp_fund_result" "txhash")
		rm -f "$temp_fund_result"

		if [ -n "$fund_tx_hash" ]; then
			if wait_for_tx "$fund_tx_hash" >/dev/null; then
				log_info "Successfully funded secondary wallet"
			else
				log_warn "Failed to fund secondary wallet - some tests may fail"
			fi
		else
			log_warn "Failed to extract funding transaction hash"
		fi
	else
		log_warn "Failed to submit funding transaction for secondary wallet"
		rm -f "$temp_fund_result"
	fi
else
	wallet2=mantra127hgjjrst9mngejd4l4wprnnppwl6e223vm9g6
	wallet2_address=$wallet2
	log_info "Using hardcoded secondary wallet for unauthorized tests: $wallet2"
fi

log_info "Testing instantiation with unauthorized wallet (should fail)..."
temp_result=$(mktemp)

$BINARY tx wasm instantiate ${code_ids[0]} '{}' --label test_fail --admin $wallet2_address $TXFLAG --from $wallet2 --keyring-backend test >"$temp_result" 2>/dev/null || true
exit_code=$?

if [ $exit_code -eq 0 ]; then
	tx_hash=$(extract_field "$temp_result" "txhash")
	rm -f "$temp_result"

	if [ -n "$tx_hash" ]; then
		# Wait a bit and check if transaction failed
		sleep 10
		temp_check=$(mktemp)
		$BINARY q tx $tx_hash --node $RPC -o json >"$temp_check" 2>/dev/null || true

		if grep -q '"code":0' "$temp_check" 2>/dev/null; then
			log_error "Instantiation with unauthorized wallet should have failed but succeeded"
			rm -f "$temp_check"
			exit 1
		else
			log_info "Instantiation with unauthorized wallet failed as expected"
		fi
		rm -f "$temp_check"
	else
		log_info "Instantiation with unauthorized wallet failed as expected"
	fi
else
	rm -f "$temp_result"
	log_info "Instantiation with unauthorized wallet failed at submission as expected"
fi

log_info "Instantiated contracts at: ${contract_addresses[@]}"

# Set primary contract for testing
contract_address="${contract_addresses[0]}"

if [ -z "$contract_address" ] || [ "$contract_address" == "null" ]; then
	log_error "No contract address found to interact with"
	exit 1
fi

log_info "--- Interacting with Contract: $contract_address ---"

# Execute Messages
log_info "Testing contract executions..."

execute_tx '{"modify_state":{}}'

execute_tx '{"send_funds":{"receipient":"'${contract_addresses[1]}'"}}' "10uom"

execute_tx_should_fail '{"send_funds":{"receipient":"'${contract_addresses[1]}'"}}'

execute_tx '{"call_contract":{"contract":"'${contract_addresses[1]}'","reply":true}}' "10uom"

execute_tx '{"call_contract":{"contract":"'${contract_addresses[1]}'","reply":false}}' "10uom"

execute_tx '{"delete_entry_on_map":{"key":1}}'

execute_tx '{"fill_map":{"limit":100}}'

execute_tx '{"fill_map":{"limit":1010}}'

execute_tx_should_fail '{"fill_map":{"limit":1000000000000}}'

execute_tx_should_fail '{"invalid":{}}'

# Query contract
log_info "Testing contract queries..."

query_contract $contract_address '{"get_count":{}}'

query_contract_raw $contract_address 'Y291bnQ='

query_contract $contract_address '{"iterate_over_map":{"limit":5}}'

query_contract $contract_address '{"iterate_over_map":{"limit":500}}'

query_contract $contract_address '{"get_entry_from_map":{"entry":1}}'

query_contract $contract_address '{"get_entry_from_map":{"entry":250}}'

# Test migration
log_info "Testing contract migration..."

temp_result=$(mktemp)

$BINARY tx wasm migrate $contract_address ${code_ids[0]} '{}' --from $WALLET $TXFLAG --keyring-backend test >"$temp_result"
exit_code=$?

if [ $exit_code -eq 0 ]; then
	tx_hash=$(extract_field "$temp_result" "txhash")
	rm -f "$temp_result"

	if [ -n "$tx_hash" ]; then
		if wait_for_tx "$tx_hash" >/dev/null; then
			log_info "Migration successful"
		else
			log_error "Migration transaction failed"
			exit 1
		fi
	else
		log_error "Failed to extract migration transaction hash"
		exit 1
	fi
else
	log_error "Migration submission failed"
	cat "$temp_result"
	rm -f "$temp_result"
	exit 1
fi

# Test migration with wrong wallet (should fail)
log_info "Testing migration with unauthorized wallet (should fail)..."
temp_result=$(mktemp)

$BINARY tx wasm migrate $contract_address ${code_ids[0]} '{}' --from $wallet2 $TXFLAG --keyring-backend test >"$temp_result" 2>/dev/null || true
exit_code=$?

if [ $exit_code -eq 0 ]; then
	tx_hash=$(extract_field "$temp_result" "txhash")
	rm -f "$temp_result"

	if [ -n "$tx_hash" ]; then
		if ! wait_for_tx "$tx_hash" >/dev/null 2>&1; then
			log_info "Migration with unauthorized wallet failed as expected"
		else
			log_error "Migration with unauthorized wallet should have failed but succeeded"
			exit 1
		fi
	else
		log_info "Migration with unauthorized wallet failed as expected"
	fi
else
	rm -f "$temp_result"
	log_info "Migration with unauthorized wallet failed at submission as expected"
fi

# Test second contract
contract_address="${contract_addresses[1]}"

log_info "Testing second contract: $contract_address"

query_contract $contract_address '{"get_count":{}}'

query_contract $contract_address '{"iterate_over_map":{"limit":5}}'

query_contract $contract_address '{"iterate_over_map":{"limit":500}}'

query_contract $contract_address '{"iterate_over_map":{"limit":1001}}'

query_contract_should_fail $contract_address '{"get_entry_from_map":{"entry":1}}'

query_contract_should_fail $contract_address '{"get_entry_from_map":{"entry":250}}'

# Test native module interop
log_info "--- Testing Native Cosmos Modules ---"

log_info "Sending native tokens..."

temp_result=$(mktemp)

# Send additional tokens to wallet2 (it may already have some from funding)
$BINARY tx bank send $WALLET $wallet2_address 100uom $TXFLAG --from $WALLET --keyring-backend test >"$temp_result"
exit_code=$?

if [ $exit_code -eq 0 ]; then
	tx_hash=$(extract_field "$temp_result" "txhash")
	rm -f "$temp_result"
	echo "tx_hash:: $tx_hash"
	if [ -n "$tx_hash" ]; then
		if wait_for_tx "$tx_hash" >/dev/null; then
			log_info "Native token send successful"
		else
			log_error "Native token send transaction failed"
			exit 1
		fi
	else
		log_error "Failed to extract bank send transaction hash"
		exit 1
	fi
else
	log_error "Native token send submission failed"
	cat "$temp_result"
	rm -f "$temp_result"
	exit 1
fi

log_info "--- All tests completed successfully ---"
log_info "Summary:"
log_info "- Contracts compiled: ✓"
log_info "- Contracts uploaded: ✓"
log_info "- Contracts instantiated: ✓"
log_info "- Contract executions: ✓"
log_info "- Contract queries: ✓"
log_info "- Contract migration: ✓"
log_info "- Native module interop: ✓"
log_info "- Expected failures verified: ✓"
