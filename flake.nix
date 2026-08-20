{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }: let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};

  in {
    devShells.${system}.default = pkgs.mkShell {
      nativeBuildInputs = with pkgs; [
        ast-grep
        (python3.withPackages (ps: [
          ps.tomlkit
        ]))
      ];
    };

    packages.${system} = {
      zedless-source = pkgs.callPackage ./nix/source.nix { };
      zedless = pkgs.callPackage ./nix/package.nix {
        source = self.packages.${system}.zedless-source;
      };
      default = self.packages.${system}.zedless;
    };
  };
}
