#!/usr/bin/env bash
set -e

project_root_path=$(realpath "$0" | sed 's|\(.*\)/.*|\1|' | cd ../ | pwd)

if [ "$1" != "--skip-verbose" ]; then
	echo -e "\nGetting artifacts versions...\n"
fi

echo -e "\033[1mContracts:\033[0m"
for artifact in artifacts/*.wasm; do
	artifact_base=$(basename "$artifact" .wasm)
	artifact_base=$(echo "$artifact_base" | sed 's/_/-/g')
	contract_path=$(find "$project_root_path/contracts" -type d -name "$artifact_base" -exec sh -c 'for dir; do [ -f "$dir/Cargo.toml" ] && echo "$dir"; done' sh {} +)

	if [ -z "$contract_path" ]; then
		printf "%-20s %s\n" "$artifact_base" ": Not found"
		continue
	fi

	version=$(grep '^version' "$contract_path/Cargo.toml" | head -n 1 | awk -F= '{print $2}' | tr -d '"')
	printf "%-20s %s\n" "$artifact_base" ": $version"
done

echo -e "\n\033[1mPackages:\033[0m"

for package in packages/*; do
	if [ -f "$package/Cargo.toml" ]; then
		version=$(awk -F= '/^version/ { print $2 }' "$package/Cargo.toml")
		version="${version//\"/}"
		printf "%-20s %s\n" "$(basename $package)" ": $version"
	else
		echo "No Cargo.toml found in $(basename $package)"
	fi
done
