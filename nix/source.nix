{
  lib,
  fetchFromGitHub,
  ast-grep,
  python3,
  stdenvNoCC
}:

let
  inherit (lib.fileset) toSource unions fileFilter;
  sourceInfo = lib.importJSON ../source-info.json;
  version = lib.removePrefix "v" sourceInfo.tag;

  zedSrc = fetchFromGitHub sourceInfo;
in

stdenvNoCC.mkDerivation{
  pname = "zedless-source";
  inherit version;

  nativeBuildInputs = [
    ast-grep
    (python3.withPackages (ps: [
      ps.tomlkit
    ]))
  ];

  src = toSource {
    root = ../.;
    fileset = unions [
      ../overlay
      (fileFilter (file: file.hasExt "py") ../.)
    ];
  };

  buildPhase = ''
    cp -r --no-preserve=mode ${zedSrc} source
    python3 patch.py
  '';

  installPhase = ''
    cp -r source $out
  '';
}
