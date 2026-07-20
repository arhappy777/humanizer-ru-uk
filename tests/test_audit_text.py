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


class EvalTests(unittest.TestCase):
    def test_eval_harness_runs_and_catches_ai_corpus(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_corpus.py"), "--format", "json"],
            check=False, capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        report = json.loads(completed.stdout.decode("utf-8"))
        ai = report["corpora"]["ai"]
        self.assertGreaterEqual(ai["files"], 10)
        self.assertGreaterEqual(ai["mean_total"], 2.0, "ИИ-корпус должен ловиться в среднем на 2+ флага")
        # Corpus may include intentionally subtle AI texts (hardcases) with zero flags.
        # Allow up to 30% miss rate; the mean_total gate handles the aggregate quality floor.
        missed = [item for item in ai["per_file"] if item["total"] == 0]
        miss_rate = len(missed) / max(len(ai["per_file"]), 1)
        self.assertLessEqual(
            miss_rate, 0.30,
            f"Больше 30% файлов корпуса не пойманы: {[m['file'] for m in missed]}",
        )


class PortTests(unittest.TestCase):
    """dist/ должен собираться из исходников и не отставать от них."""

    def test_dist_is_in_sync_with_sources(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_ports.py"), "--check"],
            check=False, capture_output=True,
        )
        self.assertEqual(
            completed.returncode, 0,
            completed.stdout.decode("utf-8", errors="replace")
            + completed.stderr.decode("utf-8", errors="replace"),
        )

    def test_chatgpt_instructions_are_a_loader_for_the_full_file(self) -> None:
        content = (ROOT / "ports" / "chatgpt-instructions.md").read_text(encoding="utf-8")
        self.assertIn(
            "humanizer-ru-uk-full.md", content,
            "инструкция обязана объявлять полный файл главным источником правил",
        )
        self.assertLessEqual(len(content), 8000, "иначе не вставится в поле Instructions Custom GPT")

    def test_full_port_contains_all_sections_and_no_repo_internals(self) -> None:
        content = (ROOT / "dist" / "humanizer-ru-uk-full.md").read_text(encoding="utf-8")
        for marker in (
            "Общие паттерны",
            "Русский профиль",
            "Український профіль",
            "Примеры «до → после»",
            "Источники и происхождение",
        ):
            self.assertIn(marker, content)
        self.assertNotIn("port:skip", content)
        self.assertNotIn("scripts/audit_text.py", content)


class SyncTests(unittest.TestCase):
    """Every code the script can emit must mean the same thing in references/,
    and every code in references/ (except LLM_ONLY_CODES) must be implemented."""

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

    def test_all_reference_codes_are_implemented_or_llm_only(self) -> None:
        """Обратный sync-тест: каждый код из references/ либо реализован в скрипте,
        либо занесён в LLM_ONLY_CODES (тогда он намеренно пропущен offline-аудитором)."""
        docs = load_reference_headings()
        script_codes: set[str] = {item.code for item in audit_text.PATTERNS}
        script_codes |= set(audit_text.STRUCTURAL_RULES.keys())
        llm_only: set[str] = audit_text.LLM_ONLY_CODES

        unimplemented = {code for code in docs if code not in script_codes and code not in llm_only}
        self.assertFalse(
            unimplemented,
            f"Коды из references/ не реализованы и не в LLM_ONLY_CODES: {sorted(unimplemented)}\n"
            f"Либо добавьте детектор, либо занесите код в LLM_ONLY_CODES в audit_text.py.",
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
        # Минимум 120 слов нужно для срабатывания по плотности (≥2% тире на слово).
        # Строим насыщенный тире текст длиннее 120 слов.
        dense = (
            "Наш релиз — это тест на выносливость. Команда — маленькая, но упрямая. "
            "Сроки — жёсткие, бюджет — смешной. Приоритет — запуск без задержек. "
            "Архитектура — простая, как и должна быть в хорошем продукте. "
            "Мониторинг — включён с первого дня производственного цикла. "
            "Тесты — написаны заранее, это помогло значительно в долгосрочной перспективе. "
            "Деплой — автоматический, люди не нужны для рутинных операций вообще. "
            "Клиенты — терпеливые, но лишнего не прощают и ждут результата. "
            "Продукт — живой, растём каждую неделю на несколько процентов стабильно. "
            "Баги — ловим в логах, фиксим в тот же день без исключений и без выходных. "
            "Метрики — считаем сами, не доверяем чужим дашбордам и готовым отчётам. "
            "Доверие — зарабатывается прозрачностью и последовательностью, не обещаниями. "
            "Команда — главный актив, всё остальное просто инструменты и ресурсы. "
            "Работаем дальше, не останавливаясь ни на один день без серьёзной и уважительной причины."
        )
        self.assertIn("S26", codes(audit_text.audit(dense, "ru")))
        dialogue = "— Привет!\n— Привет, как дела?\n— Нормально, запускаем завтра."
        self.assertNotIn("S26", codes(audit_text.audit(dialogue, "ru")))

    def test_dialogue_dash_does_not_shadow_authorial_dashes(self) -> None:
        # Нужно достаточно слов (≥120) и только авторские тире (не диалог) чтобы сработал S26.
        mixed = (
            "— Диалог начинается здесь.\n"
            + "Первый тезис — короткий, но ёмкий и работает точно.\n" * 5
            + "Второй тезис — понятный, как и было задумано с самого начала.\n" * 5
            + "Третий тезис — завершает мысль без лишних слов и паразитов.\n" * 3
        )
        result = audit_text.audit(mixed, "ru")
        self.assertIn("S26", codes(result))
        # Тире из первой строки-реплики не должны входить в count
        by_code = {item["code"]: item for item in result["findings"]}
        self.assertGreaterEqual(by_code["S26"]["count"], 5)

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

    def test_final_engagement_question_is_flagged(self) -> None:
        ending = (
            "Сегодня выключил уведомления на три часа и наконец дописал отчёт. "
            "А вы умеете вовремя нажать на паузу?"
        )
        self.assertIn("S27", codes(audit_text.audit(ending, "ru")))
        mid_text = (
            "А вы знали про новый лимит по API? Мы проверили: он реально действует. "
            "Отчёт готов, завтра покажу цифры."
        )
        self.assertNotIn("S27", codes(audit_text.audit(mid_text, "ru")))

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

    # ── Regression tests for Phase 2 fixes ────────────────────────────────────

    def test_s08_catches_phrase_without_object(self) -> None:
        """FIX: пробел убран из regex — «вывел на новый уровень» без объекта должен ловиться."""
        result = audit_text.audit("Наш подход вывел на новый уровень взаимодействие с клиентом.", "ru")
        self.assertIn("S08", codes(result))

    def test_s08_catches_ukrainian_phrase_without_object(self) -> None:
        result = audit_text.audit("Це вивело на новий рівень нашу комунікацію.", "uk")
        self.assertIn("S08", codes(result))

    def test_r01_does_not_flag_data_noun(self) -> None:
        """FIX: «данные» как существительное (именит./вин. мн.) не должно флагаться."""
        result = audit_text.audit(
            "Все данные сохранены. Мы получили данных больше, чем ожидали.", "ru"
        )
        self.assertNotIn("R01", codes(result))

    def test_r01_flags_adjective_form(self) -> None:
        """«Данный/данная/данное» как указательное прилагательное — должно флагаться."""
        result = audit_text.audit("Данный инструмент позволяет сократить время публикации.", "ru")
        self.assertIn("R01", codes(result))

    def test_s21_does_not_flag_bullet_lists(self) -> None:
        """FIX: буллет-строки исключены из streak-счёта, список задач не должен давать S21."""
        text = "Сделали за неделю:\n- убрали кеш\n- починили мобайл\n- обновили зависимости\n- задеплоили в прод\n- написали доку"
        result = audit_text.audit(text, "ru")
        self.assertNotIn("S21", codes(result))

    def test_s21_does_not_flag_dialogue_replies(self) -> None:
        """FIX: строки диалога (— реплика) исключены из streak-счёта."""
        text = "— Что думаешь?\n— Нормально.\n— Пойдёт?\n— Ок.\n— Запускаем?"
        result = audit_text.audit(text, "ru")
        self.assertNotIn("S21", codes(result))

    def test_s21_still_catches_dramatic_fragments(self) -> None:
        """После фикса реальный драматичный стрик (не буллеты, не диалог) по-прежнему флагается."""
        text = "Коротко. Честно. По делу. Без прикрас. Всё."
        result = audit_text.audit(text, "ru")
        self.assertIn("S21", codes(result))

    def test_s22_bold_threshold_not_flagged_at_four(self) -> None:
        """FIX: 4 болда (функциональных) не должны флагаться — порог повышен до 5."""
        text = (
            "Используем **Redis** для кеша, **Postgres** для данных, "
            "**S3** для медиа и **Nginx** для балансировки."
        )
        result = audit_text.audit(text, "ru")
        self.assertNotIn("S22", codes(result))

    def test_s22_bold_flagged_at_five(self) -> None:
        """5 и более болдов должны флагаться."""
        text = (
            "Стек: **Redis**, **Postgres**, **S3**, **Nginx**, **Docker**. "
            "Все компоненты проверены."
        )
        result = audit_text.audit(text, "ru")
        self.assertIn("S22", codes(result))

    def test_s26_short_text_not_flagged(self) -> None:
        """FIX: короткий текст (<120 слов) с 3 тире не должен флагаться по плотности."""
        text = (
            "— Что думаешь о запуске?\n"
            "Паша ответил коротко — без лишних слов.\n"
            "Мы переглянулись — и всё стало ясно."
        )
        result = audit_text.audit(text, "ru")
        self.assertNotIn("S26", codes(result))

    def test_s26_dialogue_lines_excluded_from_density(self) -> None:
        """FIX: тире в строках-репликах диалога не должны считаться паузами."""
        text = (
            "— Что делаем?\n"
            "— Запускаем.\n"
            "— Уверен?\n"
            "— Да.\n"
            "Решение было принято."
        )
        result = audit_text.audit(text, "ru")
        self.assertNotIn("S26", codes(result))

    def test_lang_warning_on_mismatch(self) -> None:
        """FIX: при явном --lang, не совпадающем с автодетектором, должно быть предупреждение в stderr."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "uk_text.txt"
            path.write_text(
                "Це чіткий україномовний допис без жодних ознак іншої мови.",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "--lang", "ru"],
                check=False, capture_output=True,
            )
            stderr = completed.stderr.decode("utf-8", errors="replace")
            self.assertIn("warning", stderr.lower())

    # ── New detector tests (B) ─────────────────────────────────────────────────

    def test_s28_pseudo_personal_flagged(self) -> None:
        result = audit_text.audit("Честно говоря, я не всегда верю статистике. Признаюсь, нам было сложно.", "ru")
        self.assertIn("S28", codes(result))

    def test_s28_no_false_positive(self) -> None:
        """Реальное признание без вводных фраз не флагается."""
        result = audit_text.audit("Мы облажались на старте и потеряли две недели. Вот что мы изменили.", "ru")
        self.assertNotIn("S28", codes(result))

    def test_s28_ukrainian(self) -> None:
        result = audit_text.audit("Зізнаюся, спочатку я сумнівався. Чесно кажучи, це було непросто.", "uk")
        self.assertIn("S28", codes(result))

    def test_s29_pivot_flagged(self) -> None:
        result = audit_text.audit(
            "Это не о технологиях.\nЭто о людях, которые за ними стоят.", "ru"
        )
        self.assertIn("S29", codes(result))

    def test_s29_no_false_positive(self) -> None:
        """Реальное противопоставление через «не о X, а о Y» в одном предложении без разворота."""
        result = audit_text.audit("Мы сделали выбор не о скорости, а о надёжности.", "ru")
        self.assertNotIn("S29", codes(result))

    def test_s30_marker_opener_flagged(self) -> None:
        """«Спойлер:» и «Важно:» — однозначные служебные анонсеры, должны флагаться."""
        result = audit_text.audit("Спойлер: завтра всё сломается.\nМы к этому готовились.", "ru")
        self.assertIn("S30", codes(result))

    def test_s30_upd_not_flagged(self) -> None:
        """UPD: — авторская пометка, не маркер-заголовок."""
        result = audit_text.audit("Запустили вчера. Всё прошло нормально.\nUPD: обнаружили баг, чиним.", "ru")
        self.assertNotIn("S30", codes(result))

    def test_s30_itak_not_flagged(self) -> None:
        """«Итак,» — живой авторский зачин, не флагается после фикса."""
        result = audit_text.audit("Итак, вернулся с конференции. Делюсь впечатлениями.", "ru")
        self.assertNotIn("S30", codes(result))

    def test_s30_otzhe_not_flagged(self) -> None:
        """«Отже,» — живой украинский зачин, не флагается после фикса."""
        result = audit_text.audit("Отже, повернувся з конференції. Ділюся враженнями.", "uk")
        self.assertNotIn("S30", codes(result))

    def test_s30_ukrainian(self) -> None:
        result = audit_text.audit("Важливо: це стосується всіх учасників.", "uk")
        self.assertIn("S30", codes(result))

    def test_s31_fake_lets_flagged(self) -> None:
        result = audit_text.audit("Давайте будем честными: большинство советов не работает.", "ru")
        self.assertIn("S31", codes(result))

    def test_s31_ukrainian(self) -> None:
        result = audit_text.audit("Будьмо чесними: нам було складно.", "uk")
        self.assertIn("S31", codes(result))

    def test_s31_no_false_positive(self) -> None:
        """Реальный призыв к конкретному действию без вводного «давайте»."""
        result = audit_text.audit("Давайте встретимся завтра и разберём результаты вместе.", "ru")
        self.assertNotIn("S31", codes(result))

    def test_s32_adj_triad_flagged(self) -> None:
        """≥2 триад прилагательных через «X, Y и Z» в тексте."""
        text = (
            "Сервис получился быстрым, удобным и надёжным. "
            "Команда собралась опытной, мотивированной и слаженной."
        )
        result = audit_text.audit(text, "ru")
        self.assertIn("S32", codes(result))

    def test_s32_single_triad_not_flagged(self) -> None:
        """Одна триада прилагательных — не сигнал."""
        result = audit_text.audit("Сервис получился быстрым, удобным и надёжным.", "ru")
        self.assertNotIn("S32", codes(result))

    def test_s33_chatbot_reaction_flagged(self) -> None:
        result = audit_text.audit("Звучит как план. Начинаем завтра.", "ru")
        self.assertIn("S33", codes(result))

    def test_s33_ukrainian(self) -> None:
        result = audit_text.audit("Чудове запитання! Розберемо докладніше.", "uk")
        self.assertIn("S33", codes(result))

    def test_s33_no_false_positive(self) -> None:
        """Слово «план» само по себе — не сигнал."""
        result = audit_text.audit("Наш план на квартал уже готов, начинаем завтра.", "ru")
        self.assertNotIn("S33", codes(result))

    def test_s34_fence_sitting_flagged(self) -> None:
        result = audit_text.audit("Истина где-то посередине, и у каждого подхода свои плюсы и минусы.", "ru")
        self.assertIn("S34", codes(result))

    def test_s34_with_insertion_flagged(self) -> None:
        """Регрессия: вставки между ключевыми словами не должны обходить детектор."""
        result = audit_text.audit(
            "Правда, скорее всего, посередине и зависит от задачи. Универсального ответа здесь нет.",
            "ru",
        )
        self.assertIn("S34", codes(result))

    def test_s34_universal_answer_flagged(self) -> None:
        result = audit_text.audit("Универсального ответа здесь нет, и попытки его найти проигрывают.", "ru")
        self.assertIn("S34", codes(result))

    def test_s34_ukrainian(self) -> None:
        result = audit_text.audit("Істина десь посередині — і це треба прийняти.", "uk")
        self.assertIn("S34", codes(result))

    def test_s34_no_false_positive(self) -> None:
        """Чёткая позиция — не сигнал S34."""
        result = audit_text.audit("Я считаю, что подход A лучше B в нашем контексте.", "ru")
        self.assertNotIn("S34", codes(result))

    def test_r11_nominalization_chain_flagged(self) -> None:
        """≥3 отглагольных существительных в одном предложении (проведение, внедрение, планирование)."""
        result = audit_text.audit(
            "Проведение аудита и внедрение изменений требует тщательного планирования процесса.",
            "ru",
        )
        self.assertIn("R11", codes(result))

    def test_r11_no_false_positive_normal_sentence(self) -> None:
        """Обычное предложение без цепочки отглагольных."""
        result = audit_text.audit("Мы проверили систему и обновили настройки.", "ru")
        self.assertNotIn("R11", codes(result))

    def test_r11_not_flagged_for_ukrainian(self) -> None:
        """R11 — только для русского и mixed, не флагаем украинский."""
        result = audit_text.audit(
            "Проведення аудиту безпеки та впровадження покращень вимагає ретельного планування.",
            "uk",
        )
        self.assertNotIn("R11", codes(result))

    def test_u15_en_calque_flagged(self) -> None:
        result = audit_text.audit("Ми намагаємося мати вплив на ринку і давати фідбек клієнтам.", "uk")
        self.assertIn("U15", codes(result))

    def test_u15_no_false_positive(self) -> None:
        """Нейтральное использование слов, не являющихся кальками."""
        result = audit_text.audit("Ми впливаємо на ринок і залишаємо відгук клієнтам.", "uk")
        self.assertNotIn("U15", codes(result))

    def test_u16_soviet_bureaucratese_flagged(self) -> None:
        result = audit_text.audit(
            "Компанія здійснює заходи щодо покращення якості та проводить роботу з клієнтами.", "uk"
        )
        self.assertIn("U16", codes(result))

    def test_u16_no_false_positive(self) -> None:
        """Прямой глагол — не сигнал."""
        result = audit_text.audit("Компанія покращує якість і працює з клієнтами.", "uk")
        self.assertNotIn("U16", codes(result))

    def test_s35_parallel_development_flagged(self) -> None:
        """≥3 отдельных абзаца, начинающихся с порядкового числительного."""
        text = (
            "Первое — нужно проверить данные.\n\n"
            "Второе — исправить ошибки в коде.\n\n"
            "Третье — задеплоить обновление."
        )
        result = audit_text.audit(text, "ru")
        self.assertIn("S35", codes(result))

    def test_s35_inline_ordinals_not_flagged(self) -> None:
        """«Во-первых/во-вторых» внутри одного абзаца — не сигнал S35 (нет тире)."""
        text = (
            "Хочу сказать три вещи. Во-первых, мы протестировали сервис. "
            "Во-вторых, нашли баги. В-третьих, исправили их за день."
        )
        result = audit_text.audit(text, "ru")
        self.assertNotIn("S35", codes(result))

    def test_s35_intra_paragraph_dash_ordinals_flagged(self) -> None:
        """Режим B: «Первая — …, Вторая — …, Третья — …» внутри одного абзаца флагается."""
        text = (
            "Хороший цикл строится на трёх опорах. "
            "Первая — регулярность: сверки раз в неделю. "
            "Вторая — конкретность: задавай точные вопросы. "
            "Третья — безопасность: человек делится честно только тогда, когда за честность его не наказывают."
        )
        result = audit_text.audit(text, "ru")
        self.assertIn("S35", codes(result))

    def test_s36_uniform_paragraphs_flagged(self) -> None:
        """CV длин абзацев < 0.20 при ≥5 абзацах (порог ужесточён)."""
        text = (
            "Первый абзац про запуск нашего нового проекта этим летом сезон.\n\n"
            "Второй абзац рассказывает о трудностях нашей команды в работе над.\n\n"
            "Третий абзац описывает решения которые мы нашли быстро и без.\n\n"
            "Четвёртый абзац подводит итоги нашей рабочей недели с настроем.\n\n"
            "Пятый абзац завершает рассказ о нашем запуске и следующих шагах."
        )
        result = audit_text.audit(text, "ru")
        self.assertIn("S36", codes(result))

    def test_s36_varied_paragraphs_not_flagged(self) -> None:
        """Разнородные абзацы не флагаются."""
        text = (
            "Коротко.\n\n"
            "Второй абзац намного длиннее первого и содержит существенно больше информации о нашем проекте.\n\n"
            "Третий.\n\n"
            "Ещё один длинный абзац для разнообразия длины, чтобы коэффициент вариации был высоким."
        )
        result = audit_text.audit(text, "ru")
        self.assertNotIn("S36", codes(result))

    def test_s36_four_paragraphs_cv024_not_flagged(self) -> None:
        """Регрессия: хороший текст из 4 ровных абзацев (CV~0.24) не должен флагаться после фикса."""
        # Воспроизводит структуру rw1_rewrite.txt: 4 абзаца ~35/43/24/26 слов.
        text = (
            "Обратную связь в командах чаще всего собирают слишком поздно. "
            "Решение принято, макет свёрстан, дедлайн на носу — и только теперь кто-то спрашивает.\n\n"
            "Сдвиньте этот разговор раньше. Не большой разбор раз в квартал, а короткая сверка "
            "раз в неделю, пока всё ещё можно переиграть и что-то изменить конкретно.\n\n"
            "Ещё одно: люди делятся честно, только когда за честность их потом не прилетает.\n\n"
            "Собранная так, обратная связь перестаёт быть моментом суда. Она становится рабочим материалом."
        )
        result = audit_text.audit(text, "ru")
        self.assertNotIn("S36", codes(result))

    def test_s37_mirror_ending_flagged(self) -> None:
        """Последний абзац повторяет ключевые токены первого без нового смысла."""
        # Используем одинаковые лексические формы чтобы токен-overlap сработал.
        text = (
            "Мы запустили платформу регистрации и теперь ждём пользователей.\n\n"
            "Команда работала несколько месяцев и вложила много сил в проект.\n\n"
            "Платформа регистрации запущена, пользователи уже приходят к нам."
        )
        result = audit_text.audit(text, "ru")
        self.assertIn("S37", codes(result))

    def test_s37_genuine_conclusion_not_flagged(self) -> None:
        """Финал с новым смыслом не флагается."""
        text = (
            "Мы начали год с простого MVP и минимальной команды.\n\n"
            "К лету добавили партнёров и выросли в три раза.\n\n"
            "Теперь готовимся к Series A — переговоры уже идут."
        )
        result = audit_text.audit(text, "ru")
        self.assertNotIn("S37", codes(result))


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
