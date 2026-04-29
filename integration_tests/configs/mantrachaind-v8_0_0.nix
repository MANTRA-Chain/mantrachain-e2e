{
  pkgs ? (builtins.getFlake (toString ../..)).legacyPackages.${builtins.currentSystem or "x86_64-linux"},
}:
pkgs.callPackage ../../nix/v8.0.0/default.nix {}
