# Contributing to Zedless

## Prerequisites

All the required tools are available in the `devShell`, so if you're using Nix, just run `direnv allow` or `nix develop`.

The following tools are required to execute the patch script:

- Python
- The [`tomlkit`](https://pypi.org/project/tomlkit/) Python package
- [ast-grep](https://ast-grep.github.io/)

## Patching and building the project

Clone Zed into `source/` and check out a stable release tag.

```console
$ git clone https://github.com/zed-industries/zed source
$ git -C source checkout v0.225.10
```

Patch the source. This may take a bit.

```console
$ python3 patch.py
```

Build the project, e.g. with the `release-fast` profile.

```console
$ cd source
$ cargo build --profile release-fast
```

## Iterative patching workflow

You can repeatedly run `python3 patch.py` to apply new patches. However, sometimes it's a good idea to reset the source tree with `git reset --hard`, especially when you're modifying or removing existing patches.

```console
$ git -C source reset --hard
```

Removing code via patches tends to leave behind a lot of unused variables, which `rustc` will warn you about. To be able to focus on build errors, it may be useful to disable warnings while iterating.

```console
$ RUSTFLAGS=-Awarnings cargo build --profile release-fast
```

## How to create new patches

This project wraps ast-grep rule creation in a Python script to make it easier to create many different rules based on simple configuration. [config.py](./config.py) contains high-level lists of things to remove from the code, such as functions, structs or function arguments. Start here and see if your patch can be expressed entirely with the existing rules.

The main patch script, [patch.py](./patch.py), contains logic to transform the high-level configuration into actual ast-grep rules. Add rules here if the existing rules don't cover a case required by your configuration changes, or if you need to perform a very specific patch that can't represented nicely in the configuration.

[match/](./match/) contains functions that help with the creation of common rule objects.

## Help for writing ast-grep rules

Check out the [ast-grep documentation](https://ast-grep.github.io/reference/rule.html). The [playground](https://ast-grep.github.io/reference/playground.html) provides a quick and convenient way to create and test rules.
