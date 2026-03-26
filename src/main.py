"""Main entry point for the Crypto Strategy Agent Factory."""

from __future__ import annotations

import sys

from loguru import logger

from src.config import settings

# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    level=settings.log_level,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan> | {message}",
)
logger.add(
    "logs/factory_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    rotation="10 MB",
    retention="30 days",
)


def main() -> None:
    """Run the CLI application."""
    from src.cli import app
    app()


if __name__ == "__main__":
    main()
