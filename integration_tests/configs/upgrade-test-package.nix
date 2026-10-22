{
  pkgs ? (builtins.getFlake (toString ../..)).legacyPackages.${builtins.currentSystem or "x86_64-linux"},
  useLiteMode ? false
}:
let
  builder = import ../../nix/mantrachain-builder.nix {
    inherit (pkgs) lib stdenv buildGo125Module fetchFromGitHub fetchurl pkgsStatic;
  };
  # lite mode upgrades into whichever mantrachaind is on PATH, skipping this wrapper
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
  releases = {
    genesis = builder {
      version = "v8.3.0";
      rev = "2ca2afe4ab4bb97de94719faa9d61dbb27634979";
      hash = "sha256-KFqHk7J7cua9Ra7w4kXxMhZsWPkorl5YBSDyBg6mwfo=";
      vendorHash = "sha256-vCcg2vKjNmgPP8GDdvsbIi9tveiAdP4/hmZKp2cwWD0=";
    };
    "v8.4.0" = builder {
      version = "v8.4.0";
      rev = "5c08d7bd9e2619952707dae1258d2a30bf024721";
      hash = "sha256-22W5Xit8TPIE6fAQT/TCY+v2jflK8lSvAsRioo9A+eY=";
      vendorHash = "sha256-70TdbVc+OB9phw6Z6zlCfd486jZx34GTSdmf7qSobpA=";
    };
    "v8.5.0-pre.1" = builder {
      version = "v8.5.0";
      rev = "68dfcdafdac4c470d48fea7d04864d97887bacf0";
      hash = "sha256-diXDuC+k0UnVyKPA4TZoj4srQHz1w6+ufNFcPxt9Xjw=";
      vendorHash = "sha256-v1g7ppxQB0MOIb+nU3HyTtIfZ7EYCVlAIHB2cpIM6Kc=";
    };
    "v8.7.0-pre.1" = if useLiteMode then localMantrachaindWrapper else pkgs.mantrachaind;
  };
  packageName = "upgrade-test-package" + (if useLiteMode then "-lite" else "-full");
in
pkgs.linkFarm packageName (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)
