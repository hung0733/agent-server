#!/usr/bin/env python3
"""Bootstrap TDAI memory profile files from an agent prompt file."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.i18n import t
from backend.tdai_memory.manager import MemoryManager

logger = logging.getLogger(__name__)


async def run(*, agent_id: str, prompt_file: Path) -> None:
    prompt = prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(t("scripts.bootstrap_agent_memory.prompt_file_empty") % prompt_file)

    print(t("scripts.bootstrap_agent_memory.started") % (agent_id, prompt_file))
    result = await MemoryManager.bootstrap_agent(agent_id=agent_id, prompt=prompt)

    print(t("scripts.bootstrap_agent_memory.completed") % agent_id)
    print(t("scripts.bootstrap_agent_memory.output_files"))
    for profile_name, content in result.items():
        if content:
            print(f"  - {profile_name}: {len(content)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=t("scripts.bootstrap_agent_memory.description"),
    )
    parser.add_argument("agent_id", help=t("scripts.bootstrap_agent_memory.agent_id_help"))
    parser.add_argument(
        "prompt_file",
        type=Path,
        help=t("scripts.bootstrap_agent_memory.prompt_file_help"),
    )
    args = parser.parse_args(argv)

    if not args.prompt_file.is_file():
        parser.error(t("scripts.bootstrap_agent_memory.prompt_file_missing") % args.prompt_file)

    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        asyncio.run(run(agent_id=args.agent_id, prompt_file=args.prompt_file))
    except KeyboardInterrupt:
        print(t("scripts.bootstrap_agent_memory.operation_cancelled"))
        sys.exit(130)
    except Exception as exc:
        logger.error(t("scripts.bootstrap_agent_memory.error_bootstrap_agent"), exc, exc_info=True)
        print(f"{t('scripts.bootstrap_agent_memory.error')}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()
