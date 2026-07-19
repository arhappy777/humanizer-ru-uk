from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_text.py"
SPEC = importlib.util.spec_from_file_location("audit_text", SCRIPT)
assert SPEC and SPEC.loader
audit_text = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_text
SPEC.loader.exec_module(audit_text)


HEADING_RE = re.compile(r"^###\s+([SRU]\d{2})\.\s+(.+?)\s*$", re.MULTILINE)


def codes(result: dict) -> set[str]:
    return {item["code"] for item in result["findings"]}


def normalize_title(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яёіїєґ]+", "", value.lower())


def load_reference_headings() -> dict[str, str]:
    headings: dict[str, str] = {}
    for name in ("shared-patterns.md", "russian.md", "ukrainian.md"):
        content = (ROOT / "references" / name).read_text(encoding="utf-8")
        for code, title in HEADING_RE.findall(content):
            headings[code] = title
    return headings


class FrontmatterTests(unittest.TestCase):
    """SKILL.md must stay valid per the Agent Skills spec (loader warns on extra keys)."""

    ALLOWED_KEYS = {"allowed-tools", "description", "license", "metadata", "name"}
    FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)

    def frontmatter(self) -> str:
        content = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = self.FRONTMATTER_RE.match(content)
        self.assertIsNotNone(match, "SKILL.md должен начинаться с YAML frontmatter")
        return match.group(1)

    def test_only_spec_keys_at_top_level(self) -> None:
        top_keys = set(re.findall(r"^([A-Za-z][\w-]*):", self.frontmatter(), re.MULTILINE))
        self.assertTrue(
            top_keys <= self.ALLOWED_KEYS,
            f"лишние ключи frontmatter: {sorted(top_keys - self.ALLOWED_KEYS)}",
        )
        self.assertIn("name", top_keys)
        self.assertIn("description", top_keys)

    def test_name_and_description_are_sane(self) -> None:
        block = self.frontmatter()
        name = re.search(r"^name:\s*(\S+)\s*$", block, re.MULTILINE)
        self.assertIsNotNone(name)
        self.assertEqual(name.group(1), "humanizer-ru-uk")
        description = re.search(r"^description:\s*(.+)$", block, re.MULTILINE)
        self.assertIsNotNone(description)
        self.assertLessEqual(len(description.group(1)), 1024)

    def test_version_lives_under_metadata(self) -> None:
        block = self.frontmatter()
        self.assertNotRegex(block, r"(?m)^version:", "version должен лежать в metadata, не на верхнем уровне")
        self.assertRegex(block, r"(?m)^metadata:\s*$", "нет блока metadata")
        self.assertRegex(block, r"(?m)^\s+version:\s*\"?\d+\.\d+\.\d+\"?\s*$")


class SyncTests(unittest.TestCase):
    """Every code the script can emit must mean the same thing in references/."""

    def test_pattern_codes_and_titles_match_references(self) -> None:
        docs = load_reference_headings()
        for item in audit_text.PATTERNS:
            with self.subTest(code=item.code):
                self.assertIn(item.code, docs, f"{item.code} отсутствует в references/")
                script_title = item.title_uk if item.code.startswith("U") else item.title_ru
                self.assertEqual(
                    normalize_title(script_title),
                    normalize_title(docs[item.code]),
                    f"{item.code}: скрипт «{script_title}» != каталог «{docs[item.code]}»",
                )

    def test_structural_codes_and_titles_match_references(self) -> None:
        docs = load_reference_headings()
        for code, (title_ru, title_uk) in audit_text.STRUCTURAL_RULES.items():
            with self.subTest(code=code):
                self.assertIn(code, docs, f"{code} отсутствует в references/")
                script_title = title_uk if code.startswith("U") else title_ru
                self.assertEqual(
                    normalize_title(script_title),
                    normalize_title(docs[code]),
                    f"{code}: скрипт «{script_title}» != каталог «{docs[code]}»",
                )


class LanguageTests(unittest.TestCase):
    def test_detects_russian(self) -> None:
        self.assertEqual(audit_text.detect_language("Это уже работает, но ещё не готово."), "ru")

    def test_detects_ukrainian(self) -> None:
        self.assertEqual(audit_text.detect_language("Це вже працює, але ми ще тестуємо."), "uk")

    def test_detects_intentional_mix(self) -> None:
        self.assertEqual(audit_text.detect_language("Это черновик, але він уже працює."), "mixed")

    def test_product_name_does_not_force_mixed_language(self) -> None:
        text = "Это уже наш рабочий сценарий для Дія, и мы его ещё проверяем."
        self.assertEqual(audit_text.detect_language(text), "ru")


class PatternTests(unittest.TestCase):
    def test_chatbot_wrapper_is_p0(self) -> None:
        result = audit_text.audit("Конечно! Давайте разберёмся. Вот готовый пост для публикации.", "ru")
        self.assertIn("S01", codes(result))
        by_code = {item["code"]: item for item in result["findings"]}
        self.assertGreaterEqual(by_code["S01"]["count"], 2)
        self.assertGreaterEqual(result["finding_counts"]["P0"], 1)

    def test_ukrainian_calques_are_language_specific(self) -> None:
        text = (
            "На даний момент команда приймає участь у тесті. "
            "Проблема заключається в тому, що сервіс являється нестабільним."
        )
        result = audit_text.audit(text, "uk")
        self.assertTrue({"U02", "U04", "U05", "U06"}.issubset(codes(result)))
        self.assertNotIn("R04", codes(result))

    def test_contextual_ukrainian_phrases_are_flagged_not_auto_corrected(self) -> None:
        result = audit_text.audit(
            "На протязі біля вікна лежить книга, а гроші надійшли на рахунок.", "uk"
        )
        self.assertTrue({"U08", "U11"}.issubset(codes(result)))
        by_code = {item["code"]: item for item in result["findings"]}
        self.assertEqual(by_code["U08"]["severity"], "P2")
        self.assertIn("контекст", by_code["U08"]["fix"].lower())

    def test_mixed_mode_skips_ambiguous_uk_rule(self) -> None:
        result = audit_text.audit(
            "Это чернетка українською, і задача дана команде ще вчора.", "mixed"
        )
        self.assertNotIn("U01", codes(result))
        pure_uk = audit_text.audit("Даний інструмент нам не підходить.", "uk")
        self.assertIn("U01", codes(pure_uk))

    def test_clean_russian_post_has_no_false_authorship_fields(self) -> None:
        text = (
            "Вчера проверил новый сценарий публикации. Первый запуск сломался на авторизации, "
            "второй прошёл нормально. Причина оказалась простой: токен жил в старом профиле. "
            "Перенёс настройку, повторил тест и получил нужный пост. Пока оставляю ручную проверку — "
            "одного успешного запуска мало."
        )
        result = audit_text.audit(text, "ru")
        self.assertEqual(result["finding_counts"]["P0"], 0)
        serialized = json.dumps(result, ensure_ascii=False).lower()
        self.assertNotIn("ai_probability", serialized)
        self.assertNotIn("human_score", serialized)
        self.assertNotIn("authorship", serialized)

    def test_clean_ukrainian_post_avoids_calque_flags(self) -> None:
        text = (
            "Учора перевірив новий сценарій публікації. Перший запуск зупинився на авторизації, "
            "другий пройшов нормально. Причина проста: токен лишився у старому профілі. "
            "Переніс налаштування й повторив тест. Ручну перевірку поки не прибираю."
        )
        result = audit_text.audit(text, "uk")
        self.assertFalse(any(code.startswith("U") for code in codes(result)))

    def test_uniform_rhythm_and_fragment_streak_are_structural_only(self) -> None:
        uniform = " ".join(
            [
                "Команда сегодня спокойно проверила новый рабочий сценарий.",
                "Редактор сегодня быстро исправил старую неточную формулировку.",
                "Автор сегодня лично добавил нужную ссылку внутрь.",
                "Менеджер сегодня снова сверил итоговые цифры отчёта.",
                "Дизайнер сегодня быстро подготовил новую обложку поста.",
                "Канал сегодня ровно получил готовую публикацию вовремя.",
            ]
        )
        self.assertIn("S20", codes(audit_text.audit(uniform, "ru")))
        self.assertIn("S21", codes(audit_text.audit("Коротко. Честно. По делу. А дальше — факты.", "ru")))

    def test_split_contrast_is_flagged(self) -> None:
        result = audit_text.audit("Это не реклама. Это разбор ошибок нашего запуска.", "ru")
        self.assertIn("S17", codes(result))

    def test_single_joined_contrast_is_not_flagged(self) -> None:
        result = audit_text.audit("Это не просто пост — это рабочий инструмент.", "ru")
        self.assertNotIn("S17", codes(result))

    def test_dash_density_is_flagged_but_dialogue_is_not(self) -> None:
        dense = (
            "Наш релиз — это тест на выносливость. Команда — маленькая, но упрямая. "
            "Сроки — жёсткие, бюджет — смешной. Работаем дальше без пауз."
        )
        self.assertIn("S26", codes(audit_text.audit(dense, "ru")))
        dialogue = "— Привет!\n— Привет, как дела?\n— Нормально, запускаем завтра."
        self.assertNotIn("S26", codes(audit_text.audit(dialogue, "ru")))

    def test_dialogue_dash_does_not_shadow_authorial_dashes(self) -> None:
        mixed = (
            "— Диалог начинается здесь.\n"
            "Первый тезис — короткий.\n"
            "Второй тезис — понятный.\n"
            "Третий тезис — завершает мысль."
        )
        result = audit_text.audit(mixed, "ru")
        self.assertIn("S26", codes(result))
        by_code = {item["code"]: item for item in result["findings"]}
        self.assertEqual(by_code["S26"]["count"], 3)

    def test_s17_variants_merge_into_single_finding(self) -> None:
        text = (
            "Это не просто пост — это система. Это не просто список — это метод. "
            "Это не реклама. Это разбор без прикрас."
        )
        result = audit_text.audit(text, "ru")
        s17 = [item for item in result["findings"] if item["code"] == "S17"]
        self.assertEqual(len(s17), 1)
        self.assertGreaterEqual(s17[0]["count"], 3)

    def test_findings_never_repeat_codes(self) -> None:
        noisy = (
            "Это не просто пост — это система. Это не просто список — это метод. "
            "Это не реклама. Это разбор без прикрас.\n"
            "⚡ Быстрый старт\n⚡ Простой интерфейс\n⚡ Честные цифры\n"
            "Итог: **скорость**, **простота**, **честность** и **контроль** решают."
        )
        result = audit_text.audit(noisy, "ru")
        all_codes = [item["code"] for item in result["findings"]]
        self.assertEqual(len(all_codes), len(set(all_codes)))

    def test_forced_triads_need_repetition(self) -> None:
        double = (
            "Сервис получился быстрым, удобным и надёжным. "
            "Команда работала честно, спокойно и слаженно."
        )
        self.assertIn("S18", codes(audit_text.audit(double, "ru")))
        single = "Сервис получился быстрым, удобным и надёжным, и это заметно."
        self.assertNotIn("S18", codes(audit_text.audit(single, "ru")))

    def test_hashtag_threshold_depends_on_platform(self) -> None:
        text = "Пост о запуске.\n#запуск #продукт #команда #аналитика #маркетинг #рост #стартап"
        self.assertIn("S25", codes(audit_text.audit(text, "ru")))
        relaxed = audit_text.audit(text, "ru", platform="instagram")
        self.assertNotIn("S25", codes(relaxed))

    def test_all_regular_expressions_compile(self) -> None:
        for item in audit_text.PATTERNS:
            with self.subTest(code=item.code):
                audit_text.re.compile(item.regex, audit_text.re.IGNORECASE | audit_text.re.MULTILINE)

    def test_markdown_code_examples_are_ignored(self) -> None:
        result = audit_text.audit(
            "# Приклади\n\n[Документація](https://example.com)\n\n"
            "Неправильный пример: `приймати участь`.\n\n```text\nявляється\n```",
            "uk",
        )
        self.assertNotIn("U04", codes(result))
        self.assertNotIn("U05", codes(result))
        self.assertNotIn("S21", codes(result))

    def test_blockquotes_are_not_audited(self) -> None:
        result = audit_text.audit(
            "> На даний момент команда приймає участь у тесті.\n\n"
            "Власний текст без кальок і рамок.",
            "uk",
        )
        self.assertNotIn("U02", codes(result))
        self.assertNotIn("U04", codes(result))


class InputOutputTests(unittest.TestCase):
    def test_reads_windows_1251_russian(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "post.txt"
            path.write_bytes("Это тестовый пост.".encode("cp1251"))
            self.assertEqual(audit_text.read_text(str(path)), "Это тестовый пост.")

    def test_reads_utf16_with_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "post.txt"
            path.write_text("Это тестовый пост.", encoding="utf-16")
            self.assertEqual(audit_text.read_text(str(path)), "Это тестовый пост.")

    def test_rejects_utf16_without_bom_instead_of_mojibake(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "post.txt"
            path.write_bytes("Это тестовый пост.".encode("utf-16-le"))
            with self.assertRaises(UnicodeError):
                audit_text.read_text(str(path))

    def test_cli_outputs_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "post.txt"
            path.write_text("Це вже працює.", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "--lang", "uk", "--format", "json"],
                check=False,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
            payload = json.loads(completed.stdout.decode("utf-8"))
            self.assertEqual(payload["language"], "uk")

    def test_cli_fail_on_severity_sets_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dirty = Path(temp_dir) / "dirty.txt"
            dirty.write_text("Конечно! Давайте разберёмся. Вот готовый пост.", encoding="utf-8")
            clean = Path(temp_dir) / "clean.txt"
            clean.write_text("Вчера мы выкатили релиз и починили авторизацию.", encoding="utf-8")

            gated = subprocess.run(
                [sys.executable, str(SCRIPT), str(dirty), "--lang", "ru", "--fail-on", "P0"],
                check=False, capture_output=True,
            )
            self.assertEqual(gated.returncode, 1)

            ungated = subprocess.run(
                [sys.executable, str(SCRIPT), str(dirty), "--lang", "ru"],
                check=False, capture_output=True,
            )
            self.assertEqual(ungated.returncode, 0)

            clean_gated = subprocess.run(
                [sys.executable, str(SCRIPT), str(clean), "--lang", "ru", "--fail-on", "P0"],
                check=False, capture_output=True,
            )
            self.assertEqual(clean_gated.returncode, 0)


if __name__ == "__main__":
    unittest.main()
