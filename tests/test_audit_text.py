from __future__ import annotations

import importlib.util
import json
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


def codes(result: dict) -> set[str]:
    return {item["code"] for item in result["findings"]}


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
        self.assertIn("S04", codes(result))
        self.assertGreaterEqual(result["finding_counts"]["P0"], 2)

    def test_ukrainian_calques_are_language_specific(self) -> None:
        text = (
            "На даний момент команда приймає участь у тесті. "
            "Проблема заключається в тому, що сервіс являється нестабільним."
        )
        result = audit_text.audit(text, "uk")
        self.assertTrue({"U02", "U03", "U04", "U05"}.issubset(codes(result)))
        self.assertNotIn("R04", codes(result))

    def test_contextual_ukrainian_phrases_are_flagged_not_auto_corrected(self) -> None:
        result = audit_text.audit(
            "На протязі біля вікна лежить книга, а гроші надійшли на рахунок.", "uk"
        )
        self.assertTrue({"U07", "U10"}.issubset(codes(result)))
        by_code = {item["code"]: item for item in result["findings"]}
        self.assertEqual(by_code["U07"]["severity"], "P2")
        self.assertIn("контекст", by_code["U07"]["fix"].lower())

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
        self.assertIn("T01", codes(audit_text.audit(uniform, "ru")))
        self.assertIn("T02", codes(audit_text.audit("Коротко. Честно. По делу. А дальше — факты.", "ru")))

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
        self.assertNotIn("U03", codes(result))
        self.assertNotIn("U04", codes(result))
        self.assertNotIn("T02", codes(result))


class InputOutputTests(unittest.TestCase):
    def test_reads_windows_1251_russian(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "post.txt"
            path.write_bytes("Это тестовый пост.".encode("cp1251"))
            self.assertEqual(audit_text.read_text(str(path)), "Это тестовый пост.")

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


if __name__ == "__main__":
    unittest.main()
