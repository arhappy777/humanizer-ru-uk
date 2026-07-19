#!/usr/bin/env python3
"""Прогон офлайн-аудитора по эталонным корпусам.

Структура корпуса:
- eval/ai/*.txt    — посты в типовом ИИ-стиле (входят в репозиторий);
- eval/human/*.txt — РЕАЛЬНЫЕ человеческие посты (в репозиторий не входят,
  каждый кладёт свои: один пост — один файл UTF-8).

Скрипт считает по каждому корпусу среднее число флагов, разбивку P0/P1/P2,
долю «пойманных» постов (хотя бы один флаг P1 или строже) и самые частые коды.
Если есть оба корпуса, показывает разрыв между ними. Это мера чувствительности
и ложных срабатываний редакторских правил, а не детектор авторства.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"

SPEC = importlib.util.spec_from_file_location("audit_text", ROOT / "scripts" / "audit_text.py")
assert SPEC and SPEC.loader
audit_text = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_text
SPEC.loader.exec_module(audit_text)


def corpus_stats(directory: Path) -> dict | None:
    files = sorted(directory.glob("*.txt"))
    if not files:
        return None

    per_file: list[dict] = []
    code_counter: Counter[str] = Counter()
    for path in files:
        text = path.read_text(encoding="utf-8")
        result = audit_text.audit(text, "auto")
        counts = result["finding_counts"]
        codes = sorted({item["code"] for item in result["findings"]})
        code_counter.update(codes)
        per_file.append({
            "file": path.name,
            "language": result["language"],
            "total": sum(counts.values()),
            "p0": counts["P0"],
            "p1": counts["P1"],
            "p2": counts["P2"],
            "codes": codes,
        })

    n = len(per_file)
    caught = sum(1 for item in per_file if item["p0"] + item["p1"] > 0)
    return {
        "files": n,
        "mean_total": round(sum(item["total"] for item in per_file) / n, 2),
        "mean_p0": round(sum(item["p0"] for item in per_file) / n, 2),
        "mean_p1": round(sum(item["p1"] for item in per_file) / n, 2),
        "mean_p2": round(sum(item["p2"] for item in per_file) / n, 2),
        "caught_p1_share": round(caught / n, 2),
        "top_codes": code_counter.most_common(10),
        "per_file": per_file,
    }


def render(report: dict) -> str:
    lines: list[str] = []
    for name in ("ai", "human"):
        stats = report["corpora"].get(name)
        title = "ИИ-корпус (eval/ai)" if name == "ai" else "Человеческий корпус (eval/human)"
        if stats is None:
            lines.append(f"{title}: файлов нет" + (" — добавьте свои реальные посты." if name == "human" else "."))
            lines.append("")
            continue
        lines.append(f"{title}: {stats['files']} файлов")
        lines.append(
            f"  среднее флагов на пост: {stats['mean_total']} "
            f"(P0 {stats['mean_p0']} | P1 {stats['mean_p1']} | P2 {stats['mean_p2']})"
        )
        lines.append(f"  доля постов с P1-или-строже: {stats['caught_p1_share'] * 100:.0f}%")
        lines.append("  частые коды: " + ", ".join(f"{code}×{count}" for code, count in stats["top_codes"][:8]))
        for item in stats["per_file"]:
            lines.append(
                f"    {item['file']}: {item['total']} флагов "
                f"({item['p0']}/{item['p1']}/{item['p2']}) [{', '.join(item['codes']) or '—'}]"
            )
        lines.append("")

    ai = report["corpora"].get("ai")
    human = report["corpora"].get("human")
    if ai and human:
        gap = round(ai["mean_total"] - human["mean_total"], 2)
        lines.append(
            f"Разрыв ИИ − человек: {gap} флагов на пост. "
            f"Ложные P1-срабатывания на человеческом корпусе: {human['caught_p1_share'] * 100:.0f}% постов."
        )
        lines.append("Если ложных срабатываний больше ~20%, ослабляйте правила из top_codes человеческого корпуса.")
    else:
        lines.append("Для оценки ложных срабатываний добавьте реальные посты в eval/human (один пост — один файл).")

    lines.append("")
    lines.append("Это мера качества правил, а не вывод об авторстве текста.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    audit_text.configure_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    report = {
        "corpora": {
            "ai": corpus_stats(EVAL_DIR / "ai"),
            "human": corpus_stats(EVAL_DIR / "human"),
        }
    }
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
