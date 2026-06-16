{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }: let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};
    packaging = import ./nix/packaging {
      inherit pkgs;
      inherit (self.packages.${system}) zedless;
    };
  in {
    devShells.${system}.default = pkgs.mkShell {
      nativeBuildInputs = with pkgs; [
        ast-grep
        (python3.withPackages (ps: [
          ps.toml
        ]))
      ];
    };

    packages.${system} = {
      zedless-source = pkgs.callPackage ./nix/source.nix { };
      zedless = pkgs.callPackage ./nix/package.nix {
        source = self.packages.${system}.zedless-source;
      };
      default = self.packages.${system}.zedless;
      inherit (packaging) rpm;
    };
  };
}
