{
  description = "A digest of Hydra's latest evaluation of nixpkgs master, for nixkeeper.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      treefmt-nix,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        inherit (pkgs) lib;

        # The code and its tests: the standard library only, so the workflow
        # runs it with the runner's own Python.
        src = lib.fileset.toSource {
          root = ./.;
          fileset = lib.fileset.unions [
            ./nixkeeper_hydra
            ./tests
          ];
        };

        # `nix fmt` formats everything; checks.formatting fails on anything
        # unformatted. ruff's settings live in pyproject.toml.
        treefmt = treefmt-nix.lib.evalModule pkgs {
          projectRootFile = "flake.nix";
          programs = {
            nixfmt.enable = true;
            ruff-format.enable = true;
            ruff-check.enable = true; # safe auto-fixes, e.g. import order
          };
        };

        linters = with pkgs; [
          ruff
          deadnix
          statix
          actionlint
          shellcheck # used by actionlint for the workflows' run: scripts
        ];
      in
      {
        formatter = treefmt.config.build.wrapper;

        # `nix run`: brings the digest in ./data (or the folder given) up to
        # date, as the workflow does.
        apps.default = {
          type = "app";
          program = lib.getExe (
            pkgs.writeShellScriptBin "nixkeeper-hydra" ''
              PYTHONPATH=${src} exec ${lib.getExe pkgs.python3} -m nixkeeper_hydra "$@"
            ''
          );
          meta.description = "Bring the digest of Hydra's latest evaluation up to date";
        };

        checks = {
          tests = pkgs.runCommand "nixkeeper-hydra-tests" { nativeBuildInputs = [ pkgs.python3 ]; } ''
            cd ${src}
            python3 -m unittest discover -s tests -t . -v
            touch $out
          '';
          formatting = treefmt.config.build.check self;
          lint = pkgs.runCommand "nixkeeper-hydra-lint" { nativeBuildInputs = linters; } ''
            cd ${self}
            export HOME=$TMPDIR
            ruff check --no-cache .
            deadnix --fail .
            statix check .
            # Named explicitly: on its own actionlint looks for .git, which the
            # flake source (CI's view of the repo) doesn't include.
            actionlint .github/workflows/*.yml
            shellcheck scripts/*.sh
            touch $out
          '';
        };

        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.python3
            treefmt.config.build.wrapper
          ]
          ++ linters;
        };
      }
    );
}
