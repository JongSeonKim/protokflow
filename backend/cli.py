"""ProtokFlow CLI entry point.

Registered via ``[project.scripts]`` in ``pyproject.toml`` as ``protokflow``.
"""

from __future__ import annotations


from dataclasses import dataclass

import cappa


@cappa.command(name="help", help="List available commands")
@dataclass
class Help:
    def __call__(self) -> None:
        pass


@cappa.command(name="protokflow", help="ProtokFlow CLI")
@dataclass
class Cli:
    subcommand: cappa.Subcommands[Help]


def main() -> None:
    cappa.invoke(Cli)


if __name__ == "__main__":
    main()
