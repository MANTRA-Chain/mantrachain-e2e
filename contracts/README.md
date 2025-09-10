# MANTRA DAPP TEMPLATE

Minimal contract template

## Dependencies
Just: `cargo install just`
Taplo: `cargo install taplo-cli`
Watch: `cargo install cargo-watch`

## Just recipies
The template has a justfile to help with common tasks can be executed:

execute: `just <recipe>`
```
    build                  # Builds the whole project.
    check                  # Cargo check.
    check-all              # Checks the whole project with all the feature flags.
    default                # Prints the list of recipes.
    fmt                    # Alias to the format recipe.
    format                 # Formats the rust, toml and sh files in the project.
    get-artifacts-size     # Prints the artifacts size. Optimize should be called before.
    get-artifacts-versions # Prints the artifacts versions on the current commit.
    lint                   # Runs clippy with the a feature flag if provided.
    lintfix                # Tries to fix clippy issues automatically.
    optimize               # Compiles and optimizes the contracts.
    refresh                # Cargo clean and update.
    schemas                # Build all schemas
    test                   # Tests the whole project.
    watch                  # Cargo watch.
    watch-test FEATURE=''  # Watches tests with the a feature flag if provided.
```
