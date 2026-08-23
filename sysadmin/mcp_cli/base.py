"""Command registry infrastructure for the MCP CLI."""

import argparse
from abc import ABC, abstractmethod

COMMAND_REGISTRY: dict[str, "BaseCommand"] = {}


class BaseCommand(ABC):
    """Base class for all CLI subcommands."""

    name: str = ""
    help: str = ""

    @abstractmethod
    def register_args(self, parser: argparse.ArgumentParser) -> None:
        """Add command-specific arguments to the subparser."""

    @abstractmethod
    def run(self, args: argparse.Namespace) -> None:
        """Execute the command."""


def command(cls):
    """Class decorator — auto-registers a BaseCommand subclass."""
    instance = cls()
    COMMAND_REGISTRY[instance.name] = instance
    return cls
