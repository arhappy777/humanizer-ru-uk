# Humanizer RU/UK

Agent Skill для естественных постов на русском и украинском. Помогает убрать шаблонный ИИ-стиль из черновика или написать пост по заметкам для Telegram и Instagram.

Автор и мейнтейнер: [Артём (Artem, @arhappy777)](https://github.com/arhappy777).

[Українська версія README](README.uk.md)

<div align="center">
  <img src="docs/demo.svg" alt="Офлайн-аудитор находит в посте универсальный заход, пустую важность, рекламную инфляцию и шаблонный CTA" width="780">
</div>

## Зачем он нужен

Большинство humanizer-скиллов переводят английский чеклист и обещают «обход детекторов». Здесь другая задача: читатель не должен спотыкаться о канцелярит, одинаковые абзацы, пустые крючки, фальшивую экспертность и другие следы шаблонного текста.

Скилл:

- отдельно редактирует русский и украинский, а не смешивает их в один словарь;
- знает типичные украинские кальки: `приймати участь`, `являється`, `заключається в`, `на даний момент` и другие;
- сохраняет цифры, даты, имена, ссылки, степень уверенности и реальные слова автора;
- не придумывает от первого лица опыт, клиентов, эмоции или результаты;
- подстраивается под голос автора по 2–5 его текстам;
- адаптирует форму под Telegram и Instagram;
- умеет делать аудит без переписывания;
- включает офлайн-сканер без API, телеметрии и зависимостей.

Это редактор, не детектор авторства. Он не выдаёт AI/Human-вердикт, процент «человечности» и не обещает обход систем обнаружения.

## Установка

### Claude Code

```powershell
git clone https://github.com/arhappy777/humanizer-ru-uk "$env:USERPROFILE\.claude\skills\humanizer-ru-uk"
```

### OpenClaw

```powershell
git clone https://github.com/arhappy777/humanizer-ru-uk "$env:USERPROFILE\.openclaw\skills\humanizer-ru-uk"
```

### OpenAI Codex

```powershell
git clone https://github.com/arhappy777/humanizer-ru-uk "$env:USERPROFILE\.codex\skills\humanizer-ru-uk"
```

На macOS и Linux замените путь назначения на `~/.claude/skills/humanizer-ru-uk`, `~/.openclaw/skills/humanizer-ru-uk` или `~/.codex/skills/humanizer-ru-uk`.

### ChatGPT, claude.ai и любой другой LLM

Платформы без доступа к файлам скилла используют собранные версии из папки [dist](dist/):

- **ChatGPT (Custom GPT):** содержимое [dist/chatgpt-instructions.md](dist/chatgpt-instructions.md) вставить в поле Instructions, а [dist/humanizer-ru-uk-full.md](dist/humanizer-ru-uk-full.md) приложить как Knowledge.
- **claude.ai:** добавить [dist/humanizer-ru-uk-full.md](dist/humanizer-ru-uk-full.md) в Project (или загрузить как скилл).
- **Любой другой чат:** отправить файл или вставить его в начало диалога и попросить следовать инструкции.

Файлы в `dist/` собираются командой `python scripts/build_ports.py`; их актуальность проверяет CI.

## Использование

Примеры запросов:

```text
Используй humanizer-ru-uk. Убери ИИ-шный стиль из этого поста для Telegram, но не меняй факты: [текст]
```

```text
Проведи только аудит. Покажи шаблонные места, но ничего не переписывай: [текст]
```

```text
Зроби з цих нотаток природний допис для Instagram. Нічого не вигадуй: [нотатки]
```

```text
Вот три моих старых поста для калибровки голоса: [примеры]. Теперь перепиши черновик в этом стиле: [черновик]
```

Поддерживаются четыре режима:

- `rewrite` — готовая версия поста;
- `audit` — найденные места и варианты правки;
- `draft` — пост из фактов и тезисов;
- `edit` — точечная правка файла.

## Короткий пример

До:

```text
В современном мире Telegram играет ключевую роль в коммуникации. Важно отметить, что качественный контент позволяет вывести канал на новый уровень. Это не просто тексты — это мощный инструмент взаимодействия с аудиторией.
```

После:

```text
В Telegram мало просто публиковать посты. Если первый абзац подходит любому каналу, а дальше идут одинаковые списки, читатель замечает шаблон раньше смысла. Нормальный пост начинается с того, что автор действительно хочет сказать.
```

В примере нет случайного сленга, ошибок и выдуманной личной истории. Изменились конкретные шаблонные места.

## Офлайн-аудит

Сканер показывает конкретные редакторские флаги и контекст. Он не переписывает текст и не вычисляет вероятность AI.

```powershell
python scripts/audit_text.py post.txt --lang auto
python scripts/audit_text.py post.txt --lang uk --format json
python scripts/audit_text.py post.txt --platform instagram
python scripts/audit_text.py post.txt --fail-on P0
Get-Content post.txt -Raw | python scripts/audit_text.py - --lang ru
```

`--platform` меняет платформенные пороги (хвост хештегов), `--fail-on` возвращает ненулевой код выхода для пайплайнов. Коды флагов совпадают с разделами каталогов в `references/`; синхронизацию проверяет тест в CI.

Поддерживаются UTF-8, UTF-16 с BOM и Windows-1251. Для работы нужен только Python 3.10+.

## Принцип работы

1. Зафиксировать факты и реальный опыт автора.
2. Определить язык, площадку и голос.
3. Найти общие и языковые паттерны.
4. Точечно переписать проблемные места.
5. Ещё раз сверить факты, естественность и оформление.
6. Остановиться, когда текст уже работает — не править ради нулевого числа флагов.

Подробная процедура находится в [SKILL.md](SKILL.md). Языковые каталоги и источники — в [references](references/).

## Проверка проекта

```powershell
python -m unittest discover -s tests -v
python scripts/build_ports.py --check
python scripts/eval_corpus.py
```

Тесты запускаются на Windows и Linux через GitHub Actions. `eval_corpus.py` гоняет аудитор по эталонному корпусу: ИИ-сторона лежит в [eval/ai](eval/), свои реальные посты для замера ложных срабатываний кладутся в `eval/human/` (в git не попадают). Подробности — в [eval/README.md](eval/README.md).

## Происхождение

Методика написана специально для русских и украинских социальных постов. На неё повлияли открытые MIT-проекты [blader/humanizer](https://github.com/blader/humanizer), [avoid-ai-writing](https://github.com/conorbronsdon/avoid-ai-writing), [Aboudjem/humanizer-skill](https://github.com/Aboudjem/humanizer-skill) и [humanizer-ru](https://github.com/ilyautov/humanizer-ru). Код аудитора и формулировки правил написаны заново.

Украинский профиль сверяется с действующим [стандартом «Український правопис» 2026 года](https://mova.gov.ua/storage/app/sites/19/2026/rishennja-komisiji/01-03/sdm-ukrayinskii-pravopis-vidannia.pdf).

## English quickstart

humanizer-ru-uk is an Agent Skill that edits Russian and Ukrainian social posts: it removes template AI patterns (bureaucratese, calques, empty hooks, uniform rhythm, chatbot artifacts) while preserving the author's facts and voice. It can also draft a post from raw notes. It is an editor, not an AI detector, and it does not promise detector evasion.

- **Claude Code / OpenClaw / Codex:** clone this repo into the agent's skills directory (see paths above), then ask: "убери ИИ-шный стиль из этого поста" or "зроби текст живим".
- **ChatGPT:** paste [dist/chatgpt-instructions.md](dist/chatgpt-instructions.md) into a Custom GPT's Instructions and attach [dist/humanizer-ru-uk-full.md](dist/humanizer-ru-uk-full.md) as Knowledge.
- **claude.ai or any other LLM:** add [dist/humanizer-ru-uk-full.md](dist/humanizer-ru-uk-full.md) to a Project or paste it at the start of a chat.

Four modes: `rewrite` (default), `audit` (flag only), `draft` (post from notes), `edit` (fix a file in place).

## Версии

Текущая версия — 0.4.0. История изменений — в [CHANGELOG.md](CHANGELOG.md).

## Лицензия

[MIT](LICENSE) © 2026 Artem (@arhappy777)
