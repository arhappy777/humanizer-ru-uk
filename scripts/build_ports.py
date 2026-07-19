#!/usr/bin/env python3
"""Build portable single-file versions of the skill for platforms without file access.

Outputs (committed to dist/):
- humanizer-ru-uk-full.md — SKILL.md + все каталоги references в одном файле.
  Подходит для ChatGPT (Knowledge), claude.ai (Project), Gemini или просто
  вставки в начало чата.
- chatgpt-instructions.md — компактная инструкция для поля Instructions
  Custom GPT (лимит 8000 знаков), копия ports/chatgpt-instructions.md.

`--check` пересобирает файлы в памяти и падает с кодом 1, если dist/ отстал
от исходников. Этот режим запускается в CI.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PORT_SKIP_RE = re.compile(r"<!-- port:skip -->.*?<!-- /port:skip -->\n?", re.DOTALL)
FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)
REFERENCE_LINK_RE = re.compile(r"\[([^\]]+)\]\(references/[a-z.-]+\.md\)")
VERSION_RE = re.compile(r"^\s+version:\s*\"?(\d+\.\d+\.\d+)\"?\s*$", re.MULTILINE)

REFERENCE_ORDER = (
    "shared-patterns.md",
    "russian.md",
    "ukrainian.md",
    "platforms.md",
    "examples.md",
    "sources.md",
)


def read(path: Path) -> str:
    # Нормализация перевода строк: git на Windows может выдать CRLF при checkout.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def skill_version(skill_md: str) -> str:
    match = VERSION_RE.search(skill_md)
    return match.group(1) if match else "0.0.0"


def build_full() -> str:
    skill_md = read(ROOT / "SKILL.md")
    version = skill_version(skill_md)
    body = FRONTMATTER_RE.sub("", skill_md)
    body = PORT_SKIP_RE.sub("", body)
    body = REFERENCE_LINK_RE.sub(r"«\1» (раздел ниже)", body)

    parts = [
        "# Humanizer RU/UK — полная инструкция одним файлом\n\n"
        f"> Версия {version}. Файл собран автоматически из `SKILL.md` и `references/` "
        "(`python scripts/build_ports.py`), руками не редактировать.\n"
        "> Использование: ChatGPT — приложить как Knowledge к Custom GPT; "
        "claude.ai — добавить в Project; любой другой LLM — дать файл или вставить в начало чата "
        "и попросить следовать инструкции.\n",
        body.strip(),
    ]
    for name in REFERENCE_ORDER:
        parts.append("---\n\n" + read(ROOT / "references" / name).strip() + "\n")
    return "\n\n".join(parts).rstrip() + "\n"


def build_outputs() -> dict[str, str]:
    return {
        "humanizer-ru-uk-full.md": build_full(),
        "chatgpt-instructions.md": read(ROOT / "ports" / "chatgpt-instructions.md"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify dist/ is up to date")
    args = parser.parse_args(argv)

    outputs = build_outputs()
    if args.check:
        stale = []
        for name, content in outputs.items():
            path = DIST / name
            if not path.exists() or read(path) != content:
                stale.append(name)
        if stale:
            print(f"dist/ отстал от исходников: {', '.join(stale)}. Запустите: python scripts/build_ports.py")
            return 1
        print("dist/ актуален.")
        return 0

    DIST.mkdir(exist_ok=True)
    for name, content in outputs.items():
        (DIST / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"собрано: dist/{name} ({len(content)} знаков)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
