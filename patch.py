from contextlib import chdir, contextmanager
from glob import glob
from json import dumps
from os.path import exists
from pathlib import PurePosixPath
from subprocess import run
from tempfile import NamedTemporaryFile
from config import CONFIG

import toml

import match
import match.rust

import argparse
parser = argparse.ArgumentParser(
    prog       ='Zedless Patch',
    description='Patches Zed with focus on privacy and being local-first',
    epilog     ='')
parser.add_argument('-s','--src',type=str,default="source",help="Path of the Zed's source code")
parser.add_argument('-v','--verbose',action='store_true',help="Print more info when running")

@contextmanager
def editTomlDocument(file):
    def callback(v):
        with open(file, "w") as f:
            toml.dump(v, f)
    value = None
    with open(file, "r") as f:
        value = toml.load(f)
    if value:
        yield value, callback

def editAstAdvanced(target, language, rules, rewrite, mode="all"):
    yield {
        "id": "inline",
        "language": language,
        "files": [str(PurePosixPath(target, "**/*")) if target.endswith("/") else target],
        "rule": {
            mode: rules
        },
        "fix": rewrite
    }

def mkRule(target, language, rule, fix):
    yield {
        "id": "inline",
        "language": language,
        "files": [str(PurePosixPath(target, "**/*")) if target.endswith("/") else target],
        "rule": rule,
        "fix": fix
    }

def runRules(rules):
    astGrepConfig = {
        "languageInjections": [
            {
                "hostLanguage": "rust",
                "rule": {
                    "pattern": "$_!$CONTENT"
                },
                "injected": "rust"
            }
        ]
    }
    with NamedTemporaryFile(suffix=".json", delete_on_close=False) as configFile:
        configFile.write(dumps(astGrepConfig).encode())
        configFile.close()
        # HACK: some of our rules can be applied multiple times,
        # so run ast-grep until no more changes are applied
        import sys
        import tempfile
        rules = "\n---\n".join([dumps(r) for r in rules]).encode()
        with tempfile.NamedTemporaryFile(delete=False,delete_on_close=False) as ftmp:
            ftmp.write(rules)
            ftmp.flush(); ftmp.seek(0); ftmp.close()
            while True:
                r = run([
                    "ast-grep", "scan", "--update-all",
                    "--config", configFile.name,
                    "--rule", ftmp.name,
                    "--color", "never",
                    "."
                ], capture_output=True)
                output = r.stderr.decode()
                if r.returncode != 0:
                    print(output)
                    exit(r.returncode)
                if not (output.startswith("Applied ") and output.endswith(" changes\n")):
                    break
                print(output.strip())

def deletePatterns(target, language, patterns, selector=None):
    rule = {
        "any": [
            { "pattern": pattern }
            for pattern in patterns
        ]
    }
    if selector:
        rule.update({
            "kind": selector
        })
    yield from editAstAdvanced(
        target,
        language,
        [rule],
        ""
    )

def deletePatternsAdvanced(target, language, kind, patterns):
    print("delete advanced", kind)
    yield from editAstAdvanced(
        target,
        language,
        [
            { "kind": kind },
            { "any": patterns }
        ],
        "",
        mode="all"
    )

def deleteDeclarationsAdvanced(target, elem):
    yield from editAstAdvanced(
        target,
        "rust",
        [
            elem,
            {
                "kind": "attribute_item,line_comment",
                "precedes": elem | {
                    "stopBy": {
                        "not": {
                            "kind": "attribute_item,line_comment"
                        }
                    }
                }
            }
        ],
        {
            "template": "",
            "expandEnd": {
                "regex": "^,$"
            }
        },
        mode="any",
    )

def deleteDeclarations(kind, name, identifierField="name", target="crates/"):
    yield from deleteDeclarationsAdvanced(target, {
        "kind": kind,
        "has": {
            "field": identifierField,
            "regex": f"^{name}$"
        }
    })

def replaceFunctionBody(target, selector, body):
    yield from editAstAdvanced(
        target,
        "rust",
        [
            {
                "kind": "block",
                "inside": selector,
                "not": {
                    "pattern": body
                }
            }
        ],
        body
    )

def unimplementFunction(name, target="crates/"):
    yield from replaceFunctionBody(
        target,
        match.rust.functionDefinition(name),
        "{ unimplemented!() }"
    )

def disableAnyhowFunction(target, name, errorMessage=None):
    if not errorMessage:
        errorMessage = f"function {name} has been disabled"
    body = f"{{\n    Err(anyhow::anyhow!(\"zedless: {errorMessage}\"))\n}}"
    yield from replaceFunctionBody(
        target,
        match.rust.functionDefinition(name, returnType={
            "kind": "generic_type",
            "has": {
                "field": "type",
                "regex": "^Result$"
            }
        }),
        body
    )

def disableOptionFunction(target, name):
    body = "{ None }"
    yield from replaceFunctionBody(
        target,
        match.rust.functionDefinition(name, returnType={
            "kind": "generic_type",
            "has": {
                "field": "type",
                "regex": "^Option$"
            }
        }),
        body
    )

def disableBoolFunction(target, name):
    body = "{ false }"
    yield from replaceFunctionBody(
        target,
        match.rust.functionDefinition(name, returnType={
            "kind": "primitive_type",
            "pattern": "bool"
        }),
        body
    )

def disableFutureAnyhowFunction(target, name, errorMessage=None):
    if not errorMessage:
        errorMessage = f"function {name} has been disabled"
    body = f"{{\n    async move {{ Err(anyhow::anyhow!(\"zedless: {errorMessage}\")) }}\n}}"
    yield from replaceFunctionBody(
        target,
        match.rust.functionDefinition(name, returnType={
            "kind": "bounded_type",
            "has": {
                "kind": "generic_type",
                "has": {
                    "field": "type",
                    "regex": "^Result$"
                },
                "stopBy": "end"
            }
        }),
        body
    )

def removeSymbolImports(symbol, target="crates/"):
    print("remove imports for symbol", symbol)
    yield from editAstAdvanced(
        target,
        "rust",
        [
            {
                "inside": { "kind": "use_list" },
                "any": [
                    {
                        "kind": "identifier",
                        "pattern": symbol
                    },
                    {
                        "kind": "scoped_identifier",
                        "has": {
                            "field": "name",
                            "pattern": symbol
                        }
                    }
                ],
            }
        ],
        {
            "template": "",
            "expandEnd": { "regex": "," }
        }
    )
    yield from deletePatterns("crates/", "rust", [
        f"use $CRATE::{symbol};",
        f"pub use $CRATE::{symbol};",
    ], selector="use_declaration")

def nullifyExpressions(patterns, empty, deleteStatements=False, target="crates/"):
    if deleteStatements:
        yield from deletePatterns(target, "rust", [f"{p};" for p in patterns])
    yield from editAstAdvanced(
        target,
        "rust",
        [
            { "pattern": pattern }
            for pattern in patterns
        ],
        empty,
        mode="any"
    )

def removeFieldsInDeclarations(identifier, target="crates/"):
    print("remove fields and parameters in declarations:", identifier)
    yield from editAstAdvanced(
        target,
        "rust",
        [
            {
                "all": [
                    { "kind": "field_declaration" },
                    { "has": { "field": "name", "regex": f"^{identifier}$" } }
                ]
            },
            {
                "all": [
                    { "kind": "parameter"},
                    { "has": { "field": "pattern", "pattern": identifier } }
                ]
            },
        ],
        {
            "template": "",
            "expandStart": {
                "any": [
                    { "kind": "line_comment" },
                    { "kind": "attribute_item" }
                ]
            },
            "expandEnd": { "regex": "," }
        },
        mode="any"
    )

def removeExprArguments(string, target="crates/"):
    print("remove expression arguments:", string)
    matchingIdentifier = {
        "kind": "identifier",
        "pattern": string
    }
    matchingCallExpression = {
        "kind": "call_expression",
        "has": {
            "any": [
                matchingIdentifier,
                {
                    "kind": "field_expression",
                    "pattern": f"$_.{string}"
                },
                {
                    "kind": "field_expression",
                    "pattern": f"{string}.$_"
                },
                {
                    "kind": "field_expression",
                    "pattern": f"$_.{string}().$_"
                },
            ]
        }
    }
    matchingSome = {
        "kind": "call_expression",
        "pattern": "Some($_)",
        "has": {
            "kind": "arguments",
            "has": {
                "any": [
                    matchingIdentifier,
                    matchingCallExpression
                ]
            }
        }
    }
    matchingReferenceExpression = {
        "kind": "reference_expression",
        "has": matchingIdentifier
    }
    yield from editAstAdvanced(
        target,
        "rust",
        [
            {
                "inside": {
                    "any": [
                        { "kind": "arguments" },
                        { "kind": "field_initializer_list" },
                        { "kind": "struct_pattern" },
                    ]
                }
            },
            {
                "any": [
                    matchingIdentifier,
                    matchingCallExpression,
                    matchingSome,
                    matchingReferenceExpression,
                    {
                        "kind": "shorthand_field_initializer",
                        "has": matchingIdentifier
                    },
                    {
                        "kind": "field_initializer",
                        "has": {
                            "any": [
                                matchingIdentifier,
                                matchingCallExpression,
                                matchingSome,
                                matchingReferenceExpression,
                                {
                                    "kind": "field_identifier",
                                    "regex": f"^{string}$"
                                },
                            ]
                        }
                    },
                    {
                        "kind": "field_pattern",
                        "has": {
                            "kind": "shorthand_field_identifier",
                            "regex": f"^{string}$"
                        }
                    }
                ]
            }
        ],
        {
            "template": "",
            "expandEnd": { "regex": "," }
        },
        mode="all"
    )

def removeMethodCall(name, withinArguments, target="crates/", matchRecursive=True):
    yield from mkRule(
        target,
        "rust",
        match.rust.functionCallWith(withinArguments=withinArguments, matchRecursive=matchRecursive) |
        {
            "pattern": f"$$$PREVIOUS.{name}($$$)"
        },
        "$$$PREVIOUS"
    )

def removeElementFromDelimitedList(target, elem, delimiter=","):
    delimiterRule = {
        "regex": f"^{delimiter}$"
    }
    yield from mkRule(target, "rust",
        elem | {
            "follows": delimiterRule
        },
        {
            "template": "",
            "expandStart": delimiterRule
        }
    )
    yield from mkRule(target, "rust",
        elem | {
            "precedes": delimiterRule
        },
        {
            "template": "",
            "expandEnd": delimiterRule
        }
    )
    yield from mkRule(target, "rust",
        elem,
        ""
    )

def nullifyIfStatement(target, conditionPattern: str | list[str], selectElse=True):
    if type(conditionPattern) == str:
        conditionPattern = [conditionPattern]
    yield from mkRule(target, "rust", {
        "kind": "if_expression",
        "inside": {
            "kind": "expression_statement"
        },
        "any": [
            {
                "pattern": f"if {pattern} {{ $$$THEN }} else {{ $$$ELSE }}"
            }
            for pattern in conditionPattern
        ]
    }, "$$$ELSE" if selectElse else "$$$THEN")
    if selectElse:
        yield from deletePatternsAdvanced(target, "rust", "if_expression", [
            {
                "pattern": f"if {pattern} {{ $$$ }}",
                "inside": {
                    "kind": "expression_statement"
                }
            }
            for pattern in conditionPattern
        ])

from pathlib      import Path
args = parser.parse_args()
import shutil
import os
dir_main = os.path.dirname(os.path.realpath(__file__))
with chdir(args.src):
    rules = []

    cratesToDelete = []
    for crate in CONFIG.bannedCrates:
        if exists(f"crates/{crate}"):
            cratesToDelete.append(crate)
        rules.extend(deletePatterns("crates/zed/", "rust", [
            f"{crate}::init($$$);"
        ]))
        rules.extend(deleteDeclarationsAdvanced("crates/", {
            "kind": "impl_item",
            "has": {
                "field": "trait",
                "kind": "generic_type",
                "has": {
                    "kind": "type_arguments",
                    "has": {
                        "kind": "scoped_type_identifier",
                        "regex": f"^{crate}::"
                    }
                }
            }
        }))

    crateIdentifiers = [{ "pattern": crate } for crate in CONFIG.bannedCrates]
    rules.extend(mkRule("crates/", "rust", {
        "kind": "use_declaration",
        "has": {
            "field": "argument",
            "any": [
                {
                    "kind": "scoped_identifier",
                    "has": {
                        "field": "path",
                        "any": crateIdentifiers
                    }
                },
                {
                    "kind": "scoped_use_list",
                    "has": {
                        "field": "path",
                        "any": crateIdentifiers
                    }
                },
            ]
        }
    }, ""))

    if len(cratesToDelete) > 0:
        for crate in cratesToDelete:
            tgt = Path(args.src) / 'crates' / crate
            print(f"del crate: {crate}\t@ {tgt}")
            shutil.rmtree(tgt, ignore_errors=True) #onexc=remove_readonly

        with editTomlDocument("Cargo.toml") as (data, write):
            data["workspace"]["members"] = list(filter(
                lambda m: m.removeprefix("crates/") not in cratesToDelete,
                data["workspace"]["members"]
            ))
            for crate in cratesToDelete:
                if crate in data["workspace"]["dependencies"]:
                    del data["workspace"]["dependencies"][crate]
                for prof in data["profile"]:
                    if "package" in data["profile"][prof] and crate in data["profile"][prof]["package"]:
                        del data["profile"][prof]["package"][crate]
            write(data)

        for manifest in glob("crates/*/Cargo.toml"):
            with editTomlDocument(manifest) as (data, write):
                for crate in cratesToDelete:
                    if "dependencies" in data and crate in data["dependencies"]:
                        del data["dependencies"][crate]
                    if "dev-dependencies" in data and crate in data["dev-dependencies"]:
                        del data["dev-dependencies"][crate]
                if "features" in data:
                    for feature in data["features"]:
                        data["features"][feature] = filter(
                            lambda dep: all(
                                [
                                    not dep.startswith(f"{crate}/")
                                    for crate in CONFIG.bannedCrates
                                ],
                            ), data["features"][feature]
                        )
                if data["package"]["name"] == "zed":
                    data["package"]["default-run"] = "zedless"
                    for (i, bin) in enumerate(data["bin"]):
                        if bin["name"] == "zed":
                            data["bin"][i]["name"] = "zedless"
                write(data)

    for (crate, mod) in CONFIG.bannedModules:
        tgt_src = Path(args.src) / 'crates' / crate / 'src'
        print("del mod:", crate, mod, f"\t@ {tgt_src}")
        rules.extend(deletePatterns(f"crates/{crate}/", "rust", [
            f"mod {mod};",
            f"pub mod {mod};",
            f"use crate::{mod}::$_;",
            f"pub use crate::{mod}::$_;",
            f"pub use crate::{mod}::*;",
            f"pub use {mod}::*;",
            f"{mod}::init($$$);",
            f"{crate}::{mod}::init($$$);",
        ]))
        rules.extend(mkRule(f"crates/{crate}/", "rust", {
            "kind": "use_declaration",
            "has": {
                "field": "argument",
                "any": [
                    {
                        "kind": "scoped_identifier",
                        "has": {
                            "field": "path",
                            "pattern": mod
                        }
                    },
                ]
            }
        }, ""))
        rules.extend(removeElementFromDelimitedList(f"crates/{crate}/", {
            "any": [
                {
                    "kind": "scoped_identifier",
                    "pattern": f"{mod}::$_"
                },
                {
                    "kind": "scoped_use_list",
                    "has": {
                        "kind": "identifier",
                        "pattern": mod
                    }
                },
            ],
            "inside": {
                "kind": "use_list",
                "inside": {
                    "kind": "scoped_use_list",
                    "has": {
                        "kind": "crate"
                    }
                }
            }
        }))
        rules.extend(removeElementFromDelimitedList("crates/", {
            "any": [
                {
                    "kind": "scoped_identifier",
                    "pattern": f"{mod}::$_"
                },
                {
                    "kind": "scoped_use_list",
                    "has": {
                        "kind": "identifier",
                        "pattern": mod
                    }
                },
            ],
            "inside": {
                "kind": "use_list",
                "inside": {
                    "kind": "scoped_use_list",
                    "has": {
                        "kind": "identifier",
                        "pattern": crate
                    }
                }
            }
        }))
        tgt_src = Path(args.src) / 'crates' / crate / 'src'
        tgt_mod =  [    tgt_src    /   f"{mod}.rs"]
        tgt_mod += list(tgt_src.glob(f"*/{mod}.rs"))
        for tgt in tgt_mod:
            shutil.rmtree(tgt, ignore_errors=True) #onexc=remove_readonly

    for provider in CONFIG.bannedLanguageModelProviders:
        tgt_src = Path(args.src) / 'crates' / 'language_models' / 'src' / 'provider'
        tgt = tgt_src / f"{provider.module}.rs"
        print(f"del language model provider: {provider.structPrefix} \t@ {tgt}")
        shutil.rmtree(tgt, ignore_errors=True) #onexc=remove_readonly
        rules.extend(deletePatterns("crates/language_models/", "rust", [
            f"pub mod {provider.module};",
            f"use crate::provider::{provider.module}::$_;",
            f"pub use crate::provider::{provider.module}::$_;",
        ]))
        rules.extend(removeSymbolImports(provider.lmProviderStructName, target="crates/language_models/"))
        rules.extend(removeSymbolImports(provider.settingsStructName, target="crates/language_models/"))
        rules.extend(deletePatternsAdvanced("crates/language_models/", "rust", "expression_statement", [
            {
                "has": match.rust.functionCallWith(
                    identifier={
                        "kind": "field_expression",
                        "pattern": "registry.register_provider"
                    },
                    withinArguments={
                        "kind": "call_expression",
                        "pattern": f"{provider.lmProviderStructName}::$_($$$)"
                    }
                )
            }
        ]))
        rules.extend(deletePatternsAdvanced("crates/language_models/", "rust", "let_declaration", [
            {
                "has": {
                    "kind": "identifier",
                    "pattern": provider.param
                }
            }
        ]))
        rules.extend(removeFieldsInDeclarations(provider.param, target="crates/language_models/"))
        rules.extend(removeExprArguments(provider.param, target="crates/language_models/"))

    rules.extend(deleteDeclarations("struct_item", "OpenAiLanguageModelProvider", target="crates/language_models/"))
    rules.extend(deleteDeclarations("impl_item", "OpenAiLanguageModelProvider", identifierField="type", target="crates/language_models/"))
    rules.extend(deleteDeclarations("struct_item", "OpenAiLanguageModel", target="crates/language_models/"))
    rules.extend(deleteDeclarations("impl_item", "OpenAiLanguageModel", identifierField="type", target="crates/language_models/"))
    rules.extend(mkRule("crates/language_models/src/provider/open_ai.rs", "rust",
        {
            "any": [
                { "kind": "struct_item" },
                { "kind": "impl_item" },
                { "kind": "function_item" },
                { "kind": "mod_item" },
            ],
            "not": {
                "any": [
                    match.rust.functionDefinition("add_message_content_part"),
                    match.rust.functionDefinition("append_message_to_response_items"),
                    match.rust.functionDefinition("collect_tiktoken_messages"),
                    match.rust.functionDefinition("flush_response_parts"),
                    match.rust.functionDefinition("into_open_ai"),
                    match.rust.functionDefinition("into_open_ai_response"),
                    match.rust.functionDefinition("new"),
                    match.rust.functionDefinition("map_stream"),
                    match.rust.functionDefinition("map_event"),
                    match.rust.functionDefinition("handle_completion"),
                    match.rust.functionDefinition("emit_tool_calls_from_output"),
                    match.rust.functionDefinition("token_usage_from_response_usage"),
                    match.rust.functionDefinition("push_response_image_part"),
                    match.rust.functionDefinition("push_response_text_part"),
                    match.rust.functionDefinition("tool_result_output"),
                    match.rust.implDefinition("OpenAiEventMapper"),
                    match.rust.implDefinition("OpenAiResponseEventMapper"),
                    match.rust.implDefinition("PendingResponseFunctionCall"),
                    match.rust.implDefinition("RawToolCall"),
                    match.rust.structDefinition("OpenAiEventMapper"),
                    match.rust.structDefinition("OpenAiResponseEventMapper"),
                    match.rust.structDefinition("PendingResponseFunctionCall"),
                    match.rust.structDefinition("RawToolCall"),
                ]
            }
        },
        {
            "template": "",
            "expandStart": {
                "any": [
                    { "kind": "line_comment" },
                    { "kind": "attribute_item" }
                ]
            }
        }
    ))

    for (crate, cfg) in CONFIG.perCrate.items():
        for enum in cfg.bannedEnums:
            rules.extend(deleteDeclarations("impl_item", f"{crate}::{enum}", identifierField="type"))

    for (target, cfg) in CONFIG.perDirectory.items():
        for function in cfg.bannedFunctions:
            rules.extend(deleteDeclarations("function_signature_item", function, target=target))
            rules.extend(deleteDeclarations("function_item", function, target=target))
            rules.extend(deletePatterns(target, "rust", [
                f"{function}($$$);",
                f"$_::{function}($$$);",
                f"$_.$_().{function}().$_($$$);",
                f"self.{function}($$$).await.log_err();",
                f"let $$$ = $_.{function}();",
                f"$_.update(cx, |$$$| {{ $_.{function}($$$) }})?;",
                f"$_.update(cx, |$$$| $_.{function}($$$))?;",
                f"if let $_ = cx.update({function}).await.ok() {{ $$$ }}",
                f"Self::{function}($$$).await;",
                f"async move {{ Self::{function}($$$).await }}",
            ]))
            rules.extend(deletePatternsAdvanced(target, "rust", "expression_statement", [
                {
                    "has": {
                        "kind": "call_expression",
                        "has": {
                            "kind": "field_expression",
                            "has": {
                                "kind": "field_identifier",
                                "regex": f"^{function}$"
                            }
                        }
                    }
                },
                {
                    "pattern": "cx.spawn($$$).$_($$$);",
                    "has": {
                        "kind": "call_expression",
                        "has": {
                            "kind": "arguments",
                            "has": {
                                "kind": "block",
                                "has": {
                                    "pattern": f"$$$ {function}($$$).await"
                                }
                            }
                        },
                        "stopBy": "end"
                    }
                }
            ]))
            rules.extend(removeSymbolImports(function, target=target))
            rules.extend(removeMethodCall("child", {
                "kind": "call_expression",
                "pattern": f"self.{function}($$$)"
            }, target=target, matchRecursive=False))
            rules.extend(removeMethodCall("children", {
                "kind": "call_expression",
                "pattern": f"self.{function}($$$)"
            }, target=target, matchRecursive=False))
            rules.extend(mkRule(target, "rust", {
                "kind": "if_expression",
                "pattern": f"if !self.{function}($$$) && let $L1 = $$$L2 {{ $$$THEN }} else {{ $$$ELSE }}",
            }, "if let $L1 = $$$L2 {\n    $$$THEN\n} else {\n    $$$ELSE\n}"))
            rules.extend(mkRule(target, "rust", {
                "kind": "if_expression",
                "pattern": f"if $$$COND {{ $$$THEN }} else if let Some($_) = {function}($$$) {{ $$$ }} else {{ $$$ELSE }}",
            }, "if $$$COND {\n    $$$THEN\n} else {\n    $$$ELSE\n}"))
            rules.extend(removeMethodCall("on_action", {
                "kind": "call_expression",
                "pattern": f"cx.listener(Self::{function})"
            }))
            rules.extend(mkRule(target, "rust", {
                "kind": "call_expression",
                "pattern": f"Some(Arc::new(|$$$| {{ this.{function}($$$) }}))"
            }, "None"))
            rules.extend(nullifyExpressions([
                f"{function}($$$).is_some()"
            ], "false", target=target))
            rules.extend(removeElementFromDelimitedList(target, {
                "kind": "call_expression",
                "any": [
                    {
                        "kind": "call_expression",
                        "has": {
                            "kind": "identifier",
                            "pattern": function,
                            "stopBy": {
                                "not": {
                                    "kind": "call_expression,field_expression"
                                }
                            }
                        },
                    },
                    {
                        "pattern": f"Some({function}($$$).$_())"
                    }
                ]
            }))

        for struct in cfg.bannedStructs:
            rules.extend(deleteDeclarations("struct_item", struct, target=target))
            rules.extend(deleteDeclarations("impl_item", struct, identifierField="type", target=target))
            rules.extend(removeSymbolImports(struct))
            rules.extend(deletePatterns(target, "rust", [
                f"{struct}::register($$$);",
            ]))

        for arg in cfg.bannedArguments:
            rules.extend(removeFieldsInDeclarations(arg, target=target))
            rules.extend(removeExprArguments(arg, target=target))
            rules.extend(deletePatterns(target, "rust", [
                f"self.{arg}.$_($$$);",
                f"if !$_.{arg}.is_empty() || $$$ {{ $$$ }}",
                f"if $_::get_global(cx).{arg} {{ $$$ }}",
                f"if $_::get_global(cx).{arg} && $$$ {{ $$$ }}",
                f"if $_.{arg} {{ $$$ }}",
            ]))
            rules.extend(removeMethodCall(
                "child",
                match.rust.functionCallWith({
                    "kind": "field_expression",
                    "pattern": f"self.{arg}.clone"
                }),
                target=target
            ))
            rules.extend(nullifyExpressions([
                f"self.{arg}.is_empty()",
                f"self.{arg}.is_none()",
            ], "true", deleteStatements=False, target=target))

        for local in cfg.bannedLocals:
            rules.extend(deleteDeclarations("let_declaration", local, "pattern", target=target))
            rules.extend(nullifyIfStatement(target, [
                local,
                f"{local} && $$$",
                f"$$$ && {local}",
                f"!{local}"
            ]))
            rules.extend(removeMethodCall("when", {
                "kind": "identifier",
                "pattern": local
            }, matchRecursive=False))
            rules.extend(removeMethodCall("when_some", {
                "kind": "identifier",
                "pattern": local
            }, matchRecursive=False))
            rules.extend(deletePatterns(target, "rust", [
                f"if let $_ = {local} {{ $$$ }}",
                f"if let $_ = {local}.$_() {{ $$$ }}",
                f"if let (Some($_), Some($_)) = (&{local}, &$_) {{ $$$ }}",
                f"{local}.$_($$$);",
                f"{local}.$_($$$).detach();",
                f"if !{local}.is_empty() {{ $$$ }}",
                f"$_.$_({local}, $$$);",
                f"println!($$$, {local});",
                f"{local} = $$$;",
                f"{local}.$_($$$).await?;",
                f"$_.{local} = {local};",
                f"if {local} && let $$$ = $$$ {{ $$$ }}",
            ]))
            rules.extend(mkRule(target, "rust", {
                "kind": "if_expression",
                "pattern": f"if {local} {{ $$$ }} else if $$$COND {{ $$$THEN }} else {{ $ELSE }}"
            }, "if $$$COND {\n    $$$THEN\n} else {\n    $ELSE\n}"))
            rules.extend(mkRule(target, "rust", {
                "kind": "if_expression",
                "pattern": f"if $$$COND {{ $$$THEN }} else if let Some($_) = &{local} {{ $$$ }} else {{ $$$ELSE }}"
            }, "if $$$COND {\n    $$$THEN\n} else {\n    $$$ELSE\n}"))
            rules.extend(nullifyExpressions([
                f"{local}.is_some()"
            ], "false", target=target))
            rules.extend(mkRule(target, "rust", {
                "kind": "binary_expression"
            } | match.any(
                {
                    "pattern": f"$OTHER || {local}"
                },
                {
                    "pattern": f"{local} || $OTHER"
                },
            ), "$OTHER"))
            rules.extend(removeElementFromDelimitedList(target, {
                "kind": "identifier",
                "pattern": local,
                "inside": {
                    "kind": "token_tree",
                    "inside": {
                        "kind": "macro_invocation"
                    }
                }
            }))
            rules.extend(mkRule(target, "rust", {
                "pattern": f"let ($A, $B, {local}) = if $$$COND {{ ($ATHEN, $BTHEN, $_) }} else {{ ($AELSE, $BELSE, $_) }};"
            }, {
                "template": "let ($A, $B) = if $$$COND {\n    ($ATHEN, $BTHEN)\n} else {\n    ($AELSE, $BELSE)\n};"
            }))
            rules.extend(mkRule(target, "rust", {
                "pattern": f"let $VAR = if {local} {{ $$$ }} else {{ $ELSE }};"
            }, {
                "template": "let $VAR = $ELSE;"
            }))
            rules.extend(mkRule(target, "rust", {
                "pattern": f"add_panel_when_ready({local}, $$$)"
            }, {
                "template": "",
                "expandEnd": {
                    "regex": "^,$"
                }
            }))
            rules.extend(mkRule(target, "rust", {
                "kind": "call_expression",
                "pattern": f"{local}.as_ref().map($$$).or($$$OR).unwrap_or_default()"
            }, "($$$OR).unwrap_or_default()"))

        for action in cfg.bannedActions:
            rules.extend(removeMethodCall("register_action", {
                "kind": "closure_expression",
                "has": {
                    "kind": "closure_parameters",
                    "has": {
                        "kind": "parameter",
                        "has": {
                            "field": "type",
                            "has": {
                                "kind": "type_identifier",
                                "regex": f"^{action}$",
                                "stopBy": "end"
                            }
                        }
                    }
                }
            }, target=target, matchRecursive=False))
            rules.extend(removeMethodCall("on_action", {
                "kind": "closure_expression",
                "has": {
                    "kind": "closure_parameters",
                    "has": {
                        "kind": "parameter",
                        "has": {
                            "field": "type",
                            "has": {
                                "kind": "type_identifier",
                                "regex": f"^{action}$",
                                "stopBy": "end"
                            }
                        }
                    }
                }
            }, target=target, matchRecursive=True))
            rules.extend(deletePatternsAdvanced(target, "rust", "expression_statement", [
                {
                    "any": [
                        {
                            "pattern": "workspace.register_action($$$);"
                        },
                        {
                            "pattern": "cx.on_action($$$);"
                        }
                    ],
                    "has": match.rust.functionCallWith(withinArguments={
                        "has": {
                            "kind": "closure_parameters",
                            "has": {
                                "kind": "parameter",
                                "has": {
                                    "field": "type",
                                    "has": {
                                        "kind": "type_identifier",
                                        "regex": f"^{action}$",
                                        "stopBy": "end"
                                    }
                                }
                            }
                        }
                    })
                }
            ]))

        for variant in cfg.bannedEnumVariants:
            scopedIdentifier = {
                "kind": "scoped_identifier",
                "pattern": f"$_::{variant}"
            }
            rules.extend(deleteDeclarations("enum_variant", variant, target=target))
            rules.extend(deletePatternsAdvanced(target, "rust", "match_arm", [
                {
                    "has": {
                        "kind": "match_pattern",
                        "has": {
                            "any": [
                                scopedIdentifier,
                                {
                                    "kind": "tuple_struct_pattern",
                                    "all": [
                                        {
                                            "has": {
                                                "field": "type",
                                                "pattern": "Some"
                                            }
                                        },
                                        {
                                            "has": scopedIdentifier,
                                        }
                                    ]
                                },
                            ]
                        }
                    }
                }
            ]))
            rules.extend(removeElementFromDelimitedList(target, {
                "pattern": f"$_::{variant}",
                "inside": {
                    "kind": "or_pattern",
                    "inside": {
                        "kind": "match_pattern",
                        "stopBy": "end"
                    }
                }
            }, delimiter="|"))
            rules.extend(removeElementFromDelimitedList(target, {
                "kind": "tuple_expression",
                "pattern": f"($_::{variant}, $$$)",
                "inside": {
                    "kind": "array_expression"
                }
            }))
            rules.extend(removeMethodCall("item", scopedIdentifier))
            rules.extend(nullifyIfStatement(target, [
                f"$$$ == $_::{variant}",
                f"$$$ == $_::{variant} && $$$",
            ]))
            rules.extend(deletePatterns(target, "rust", [
                f"$_.push($_::{variant});",
            ], "expression_statement"))

        for enum in cfg.bannedEnums:
            rules.extend(deleteDeclarations("enum_item", enum, target=target))
            rules.extend(deleteDeclarations("impl_item", enum, identifierField="type", target=target))
            rules.extend(removeSymbolImports(enum))
            rules.extend(deleteDeclarationsAdvanced(target, {
                "kind": "impl_item",
                "has": {
                    "field": "trait",
                    "kind": "generic_type",
                    "has": {
                        "kind": "type_arguments",
                        "has": {
                            "kind": "type_identifier",
                            "regex": f"^{enum}$"
                        }
                    }
                }
            }))

        for function in cfg.disabledFunctions:
            rules.extend(disableAnyhowFunction(target, function))
            rules.extend(disableOptionFunction(target, function))
            rules.extend(disableBoolFunction(target, function))
            rules.extend(disableFutureAnyhowFunction(target, function))

        for (original, replacement) in cfg.stringReplacements:
            rules.extend(mkRule(target, "rust", {
                "pattern": f"\"{original}\""
            }, f"\"{replacement}\""))

    bannedMenuItemArgumentsSelector = {
        "kind": "token_tree",
        "follows": {
            "kind": "identifier",
            "pattern": "action",
        },
        "has": {
            "kind": "string_literal",
            "any": [
                { "pattern": f"\"{actionName}\"" }
                for actionName in [
                    "Check for Updates",
                    "Email Us...",
                    "Join the Team",
                    "View Release Notes Locally",
                    "View Telemetry",
                ]
            ]
        }
    }
    def stackPrecedes(item, count):
        if count == 1:
            return {
                "kind": "identifier",
                "precedes": item
            }
        else:
            return stackPrecedes({ "precedes": item }, count-1)
    rules.extend(mkRule("crates/zed/src/zed/app_menus.rs", "rust", {
        "any": [
            bannedMenuItemArgumentsSelector,
            stackPrecedes(bannedMenuItemArgumentsSelector, 1),
            stackPrecedes(bannedMenuItemArgumentsSelector, 3)
        ]
    }, {
        "template": "",
        "expandEnd": {
            "regex": "^,$"
        },
        "expandStart": {
            "regex": "^::$"
        }
    }))
    for (originalActionName, actionName, url) in [
        ("About Zed", "About Zedless", None),
        ("Quit Zed", "Quit Zedless", None),
        ("File Bug Report...", "File a bug report...", "https://github.com/zedless-editor/zedless/issues/new"),
        ("Request Feature...", "Request a feature...", "https://github.com/zedless-editor/zedless/discussions/new?category=ideas"),
        ("Documentation", "Documentation (zed.dev)", None),
        ("Zed Repository", "Zedless Repository", "https://github.com/zedless-editor/zedless"),
        ("Zed Twitter", "Zedless on Matrix", "https://matrix.to/#/#zedless:privatevoid.net"),
    ]:
        # HACK
        assert actionName != originalActionName
        if url:
            rules.extend(mkRule("crates/zed/src/zed/app_menus.rs", "rust", {
                "kind": "token_tree",
                "follows": {
                    "kind": "identifier",
                    "pattern": "action",
                },
                "has": {
                    "kind": "string_literal",
                    "pattern": f"\"{originalActionName}\""
                }
            }, f"(\"{actionName}\", super::OpenBrowser {{ url: \"{url}\".into() }})"))
        else:
            rules.extend(mkRule("crates/zed/src/zed/app_menus.rs", "rust", {
                "kind": "string_literal",
                "pattern": f"\"{originalActionName}\"",
                "inside": {
                    "kind": "token_tree",
                    "follows": {
                        "kind": "identifier",
                        "pattern": "action"
                    }
                }
            }, f"\"{actionName}\""))

    rules.extend(mkRule("crates/zed/src/zed/app_menus.rs", "rust", { "pattern": "\"Zed\"" }, "\"Zedless\""))

    rules.extend(mkRule("crates/settings_content/", "rust", {
        "kind": "enum_variant",
        "has": {
            "field": "name",
            "pattern": "None"
        },
        "inside": {
            "kind": "enum_variant_list",
            "inside": {
                "kind": "enum_item",
                "has": {
                    "field": "name",
                    "regex": "^EditPredictionProvider$"
                }
            }
        },
        "not": {
            "follows": {
                "kind": "attribute_item",
                "pattern": "#[default]"
            }
        }
    }, "#[default]\nNone"))

    rules.extend(removeMethodCall("when", {
        "pattern": "cx.has_flag::<PredictEditsRatePredictionsFeatureFlag>()",
    }, matchRecursive=False))

    rules.extend(nullifyExpressions([
        "telemetry::event!($$$)",
    ], "()", deleteStatements=True))

    rules.extend(deletePatterns("crates/", "rust", [
        "let (telemetry, is_via_ssh) = { $$$ };",
        "use $$$::telemetry::{$$$};",
    ]))

    rules.extend(removeMethodCall("child", match.rust.functionCall("render_telemetry_section"), target="crates/onboarding/"))

    # The `None` here is an Option<ActionLogTelemetry>, which was removed
    rules.extend(editAstAdvanced("crates/agent_ui/", "rust", [
        {
            "pattern": "action_log.keep_all_edits(None, $A)"
        }
    ], "action_log.keep_all_edits($A)"))

    rules.extend(mkRule("crates/remote/", "rust", {
        "kind": "block",
        "pattern": "{ $$$PREV if binary_exists_on_server { return Ok(dst_path); } $$$ }"
    }, {
        "template": "{\n$$$PREV\nif binary_exists_on_server { Ok(dst_path) } else { Err(anyhow::anyhow!(\"zedless: no remote server binary found on target\")) }\n}"
    }))

    rules.extend(deletePatterns("crates/", "rust", [
        "if cx.is_staff() { $$$ }"
    ]))

    rules.extend(mkRule("crates/edit_prediction/", "rust", {
        "kind": "block",
        "inside": {
            "kind": "else_clause"
        },
        "has": {
            "kind": "call_expression",
            "pattern": "EditPredictionStore::send_v3_request($$$)",
            "stopBy": "end"
        }
    }, "{ None }"))

    # Cleanup
    rules.extend(deletePatterns("crates/", "rust", [
        "if $$$ {} else {}"
    ]))
    rules.extend(mkRule("crates/", "rust", {
        "pattern": "if $$$ {}",
        "not": {
            "has": {
                "kind": "else_clause"
            }
        }
    }, ""))
    rules.extend(mkRule("crates/", "rust", {
        "kind": "binary_expression",
        "pattern": "$_ && $_",
        "has": {
            "kind": "boolean_literal",
            "regex": "^false$"
        }
    }, "false"))
    rules.extend(mkRule("crates/", "rust", {
        "kind": "expression_statement",
        "pattern": "cx.background_spawn($$$).detach();",
        "has": {
            "kind": "call_expression",
            "has": {
                "kind": "arguments",
                "has": {
                    "kind": "block",
                    "not": {
                        "has": {
                            "not": {
                                "kind": "let_declaration"
                            },
                            "pattern": "$_"
                        }
                    }
                }
            },
            "stopBy": "end"
        }
    }, ""))

    runRules(rules)

    src = Path(dir_main) / 'overlay' / '.'
    tgt = Path(args.src)
    if args.verbose:
        print(f"  {src}\n →{tgt}")
    shutil.copytree(src,tgt,dirs_exist_ok=True)
