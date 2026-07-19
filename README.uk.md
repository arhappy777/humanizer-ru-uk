# Humanizer RU/UK

Agent Skill для природних дописів українською та російською. Допомагає прибрати шаблонний ШІ-стиль із чернетки або написати допис із нотаток для Telegram та Instagram.

Автор і мейнтейнер: [Артем (Artem, @arhappy777)](https://github.com/arhappy777).

[README російською](README.md)

## Навіщо він потрібен

Це не інструмент для «обходу детекторів». Його мета — прибрати те, що заважає читачеві: канцелярит, однакові абзаци, порожні гачки, удавану експертність, російські кальки та механічне оформлення.

Скіл:

- окремо редагує українську й російську;
- знаходить поширені кальки: `приймати участь`, `являється`, `заключається в`, `на даний момент` та інші;
- зберігає числа, дати, імена, посилання, ступінь упевненості й реальні слова автора;
- не вигадує від першої особи досвід, клієнтів, емоції або результати;
- налаштовується під голос автора за 2–5 його текстами;
- адаптує форму під Telegram та Instagram;
- проводить аудит без переписування;
- має офлайн-сканер без API, телеметрії та зовнішніх залежностей.

Це редактор, а не детектор авторства. Він не видає вердикт AI/Human, відсоток «людяності» й не обіцяє обхід систем виявлення.

## Встановлення

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

На macOS і Linux використовуйте `~/.claude/skills/humanizer-ru-uk`, `~/.openclaw/skills/humanizer-ru-uk` або `~/.codex/skills/humanizer-ru-uk`.

### ChatGPT, claude.ai та будь-який інший LLM

Платформи без доступу до файлів скіла використовують зібрані версії з папки [dist](dist/): для ChatGPT вставте [dist/chatgpt-instructions.md](dist/chatgpt-instructions.md) у поле Instructions і прикладіть [dist/humanizer-ru-uk-full.md](dist/humanizer-ru-uk-full.md) як Knowledge; для claude.ai додайте повний файл у Project; в іншому чаті — надішліть файл і попросіть слідувати інструкції.

## Використання

```text
Використай humanizer-ru-uk. Прибери ШІ-шний стиль із цього допису для Telegram, але не змінюй факти: [текст]
```

```text
Проведи лише аудит. Покажи шаблонні місця, але нічого не переписуй: [текст]
```

```text
Зроби з цих нотаток природний допис для Instagram. Нічого не вигадуй: [нотатки]
```

```text
Ось три мої старі дописи для калібрування голосу: [приклади]. Тепер перепиши чернетку в цьому стилі: [чернетка]
```

Режими: `rewrite`, `audit`, `draft` та `edit`.

## Короткий приклад

До:

```text
У сучасному світі Telegram відіграє ключову роль у комунікації. Варто зазначити, що якісний контент дозволяє вивести канал на новий рівень. Це не просто тексти — це потужний інструмент взаємодії з аудиторією.
```

Після:

```text
У Telegram замало просто публікувати дописи. Якщо перший абзац пасує будь-якому каналу, а далі йдуть однакові списки, читач помічає шаблон раніше за зміст. Нормальний допис починається з того, що автор справді хоче сказати.
```

У прикладі немає випадкового сленгу, помилок чи вигаданої особистої історії. Змінилися конкретні шаблонні місця.

## Офлайн-аудит

```powershell
python scripts/audit_text.py post.txt --lang auto
python scripts/audit_text.py post.txt --lang uk --format json
python scripts/audit_text.py post.txt --platform instagram
python scripts/audit_text.py post.txt --fail-on P0
Get-Content post.txt -Raw | python scripts/audit_text.py - --lang uk
```

Сканер показує конкретні редакторські сигнали. Він не переписує текст, не визначає авторство й не рахує «ймовірність AI». `--platform` змінює платформні пороги (хвіст хештегів), `--fail-on` повертає ненульовий код виходу для пайплайнів. Коди сигналів збігаються з розділами каталогів у `references/`; синхронізацію перевіряє тест у CI. Підтримуються UTF-8, UTF-16 із BOM та Windows-1251; потрібен Python 3.10+.

## Як працює метод

1. Зафіксувати факти й справжній досвід автора.
2. Визначити мову, майданчик і голос.
3. Знайти спільні та мовні патерни.
4. Точково переписати проблемні місця.
5. Ще раз звірити факти, природність та оформлення.
6. Зупинитися, коли текст уже працює.

Повна процедура — у [SKILL.md](SKILL.md). Мовні каталоги та джерела — у [references](references/).

## Походження

Методику написано спеціально для українських і російських соціальних дописів. На неї вплинули відкриті MIT-проєкти [blader/humanizer](https://github.com/blader/humanizer), [avoid-ai-writing](https://github.com/conorbronsdon/avoid-ai-writing), [Aboudjem/humanizer-skill](https://github.com/Aboudjem/humanizer-skill) і [humanizer-ru](https://github.com/ilyautov/humanizer-ru). Код аудитора та формулювання правил написано заново.

Український профіль спирається на чинний [стандарт «Український правопис» 2026 року](https://mova.gov.ua/storage/app/sites/19/2026/rishennja-komisiji/01-03/sdm-ukrayinskii-pravopis-vidannia.pdf).

## Версії

Поточна версія — 0.3.1. Історія змін — у [CHANGELOG.md](CHANGELOG.md).

## Ліцензія

[MIT](LICENSE) © 2026 Artem (@arhappy777)
