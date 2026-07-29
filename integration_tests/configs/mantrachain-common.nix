{ pkgs }:
let
  localMantrachaindWrapper = pkgs.writeShellScriptBin "mantrachaind" ''
    WRAPPER_DIR="$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")"
    REAL_MANTRACHAIND=""
    IFS=':' read -ra PATH_ARRAY <<< "$PATH"
    for dir in "''${PATH_ARRAY[@]}"; do
      if [ "$dir" != "$WRAPPER_DIR" ] && [ -x "$dir/mantrachaind" ]; then
        REAL_MANTRACHAIND="$dir/mantrachaind"
        break
      fi
    done
    if [ -z "$REAL_MANTRACHAIND" ] || [ ! -x "$REAL_MANTRACHAIND" ]; then
      echo "Error: mantrachaind not found in PATH" >&2
      exit 1
    fi
    exec "$REAL_MANTRACHAIND" "$@"
  '';
in
{
  localMantrachaindWrapper = localMantrachaindWrapper;
}
