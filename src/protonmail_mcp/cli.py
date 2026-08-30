"""Console entry point for the protonmail-mcp command."""

import argparse

from protonmail_mcp import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="protonmail-mcp",
        description=(
            "MCP server for ProtonMail via ProtonMail Bridge. Runs the stdio MCP server by default."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Run the MCP server over stdio (default)")
    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        from protonmail_mcp.server import run

        run()


if __name__ == "__main__":
    main()
