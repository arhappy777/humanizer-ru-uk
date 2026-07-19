#!/usr/bin/env python3
"""Offline editorial audit for Russian and Ukrainian social posts.

The script reports concrete style patterns. It does not classify authorship,
calculate an "AI probability", rewrite text, or send data over the network.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ]+(?:['’][A-Za-zА-Яа-яЁёІіЇїЄєҐґ]+)?")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n{2,}")
SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}


@dataclass(frozen=True)
class Pattern:
    code: str
    languages: tuple[str, ...]
    severity: str
    category: str
    regex: str
    title_ru: str
    title_uk: str
    why_ru: str
    why_uk: str
    fix_ru: str
    fix_uk: str
    min_count: int = 1


def pattern(
    code: str,
    languages: Sequence[str],
    severity: str,
    category: str,
    regex: str,
    title_ru: str,
    title_uk: str,
    why_ru: str,
    why_uk: str,
    fix_ru: str,
    fix_uk: str,
    min_count: int = 1,
) -> Pattern:
    return Pattern(
        code,
        tuple(languages),
        severity,
        category,
        regex,
        title_ru,
        title_uk,
        why_ru,
        why_uk,
        fix_ru,
        fix_uk,
        min_count,
    )


PATTERNS: tuple[Pattern, ...] = (
    pattern(
        "S01", (), "P0", "chatbot-artifact",
        r"\b(?:конечно|звісно)\s*[!,.]?\s*(?:давайте|давай|розглянемо|розгляньмо)\b|"
        r"\b(?:если|якщо)\s+(?:хотите|хочете),?\s+(?:я\s+)?(?:могу|можу)\b|"
        r"\b(?:надеюсь|сподіваюся),?\s+(?:это|це)\s+(?:было|було)\s+(?:полезн\w*|корисн\w*)",
        "Служебная реплика чатбота", "Службова репліка чатбота",
        "Фраза обращена к пользователю чата, а не к читателю поста.",
        "Фраза звернена до користувача чату, а не до читача допису.",
        "Удалить рамку и начать с мысли автора.",
        "Прибрати рамку й почати з думки автора.",
    ),
    pattern(
        "S02", (), "P0", "chatbot-artifact",
        r"cite(?:turn|turn)\d+(?:search|view|fetch)\d+|contentReference\[[^\]]+\]|"
        r"oai_citation|oaicite|\[attached_file:\d+\]|grok_card",
        "Внутренний токен или сломанная цитата", "Внутрішній токен або зламане цитування",
        "В тексте остался технический след интерфейса.",
        "У тексті залишився технічний слід інтерфейсу.",
        "Удалить токен; важную ссылку заменить реальным источником.",
        "Видалити токен; важливе посилання замінити справжнім джерелом.",
    ),
    pattern(
        "S03", (), "P0", "placeholder",
        r"\[(?:встав(?:ьте|ити)|добав(?:ьте|ити)|укажите|вкажіть|имя|ім['’]?я|"
        r"название|назва|ссылка|посилання|источник|джерело|todo)[^\]]*\]|"
        r"\{(?:имя|ім['’]?я|название|назва|ссылка|посилання|источник|джерело)[^}]*\}|"
        r"\b20\d{2}-XX-XX\b",
        "Незаполненный шаблон", "Незаповнений шаблон",
        "Такой фрагмент нельзя оставлять в публикации.",
        "Такий фрагмент не можна залишати в публікації.",
        "Заполнить известным фактом или удалить.",
        "Заповнити відомим фактом або видалити.",
    ),
    pattern(
        "S04", (), "P0", "chatbot-artifact",
        r"\b(?:вот|ось)\s+(?:готов(?:ый|а|ое|і)|финальн\w+|підсумков\w+)\s+"
        r"(?:пост|текст|вариант|версія|варіант|допис)\b",
        "Обёртка перед готовым текстом", "Обгортка перед готовим текстом",
        "Это пояснение ассистента, а не часть поста.",
        "Це пояснення асистента, а не частина допису.",
        "Удалить обёртку.", "Видалити обгортку.",
    ),
    pattern(
        "S05", (), "P1", "generic-opening",
        r"\b(?:в современном мире|в эпоху (?:цифровизации|быстрых|стремительных)\w*|"
        r"сегодня как никогда|у сучасному світі|в епоху (?:цифровізації|швидких|стрімких)\w*|"
        r"сьогодні як ніколи)\b",
        "Универсальный заход", "Універсальний вступ",
        "Фразу можно поставить перед постом почти на любую тему.",
        "Фразу можна поставити перед дописом майже на будь-яку тему.",
        "Начать с конкретного события, наблюдения или вывода.",
        "Почати з конкретної події, спостереження або висновку.",
    ),
    pattern(
        "S06", (), "P1", "empty-importance",
        r"\b(?:важно отметить|нельзя не отметить|игра(?:ет|ют) ключевую роль|"
        r"невозможно переоценить|варто зазначити|не можна не згадати|"
        r"відігра(?:є|ють) ключову роль|неможливо переоцінити)\b",
        "Пустая сигнализация важности", "Порожня сигналізація важливості",
        "Оценочная рамка часто заменяет доказательство или последствие.",
        "Оцінна рамка часто замінює доказ або наслідок.",
        "Убрать рамку и показать, что именно изменилось.",
        "Прибрати рамку й показати, що саме змінилося.",
    ),
    pattern(
        "S07", (), "P1", "vague-attribution",
        r"\b(?:эксперты (?:считают|отмечают|говорят)|исследования показывают|"
        r"по мнению специалистов|експерти (?:вважають|зазначають|кажуть)|"
        r"дослідження показують|на думку фахівців)\b",
        "Источник без имени", "Джерело без назви",
        "Утверждение прикрыто безымянным авторитетом.",
        "Твердження прикрите безіменним авторитетом.",
        "Назвать источник или переписать как честное мнение.",
        "Назвати джерело або переписати як чесну думку.",
    ),
    pattern(
        "S08", (), "P1", "promotional-inflation",
        r"\b(?:открыва(?:ет|ют) новые горизонты|раскрыва(?:ет|ют) потенциал|"
        r"выводит? .{0,30} на новый уровень|революционн(?:ый|ая|ое|ые) подход|"
        r"відкрива(?:є|ють) нові горизонти|розкрива(?:є|ють) потенціал|"
        r"виводить? .{0,30} на новий рівень|революційн(?:ий|а|е|і) підхід)\b",
        "Рекламная инфляция", "Рекламне перебільшення",
        "Громкая формула не сообщает проверяемого эффекта.",
        "Гучна формула не повідомляє перевірного ефекту.",
        "Заменить фактическим действием или результатом из исходника.",
        "Замінити фактичною дією або результатом із джерела.",
    ),
    pattern(
        "S09", (), "P1", "generic-conclusion",
        r"\b(?:в заключение(?: можно сказать)?|подводя итоги|резюмируя вышесказанное|"
        r"підсумовуючи(?:,? можна сказати)?|на завершення варто зазначити|"
        r"резюмуючи сказане)\b",
        "Шаблонный вывод", "Шаблонний висновок",
        "Финальная рамка обычно повторяет уже сказанное.",
        "Фінальна рамка зазвичай повторює вже сказане.",
        "Закончить последствием или последней сильной мыслью.",
        "Завершити наслідком або останньою сильною думкою.",
    ),
    pattern(
        "S10", (), "P1", "fake-first-person",
        r"\b(?:меня особенно впечатлил\w*|я (?:был|была) пораж[её]н\w*|"
        r"по моему личному опыту|мене особливо вразил\w*|я (?:був|була) вражен\w*|"
        r"з мого особистого досвіду)\b",
        "Шаблонная личная эмоция", "Шаблонна особиста емоція",
        "Первое лицо требует проверки по исходнику или образцам автора.",
        "Перша особа потребує перевірки за джерелом або зразками автора.",
        "Не добавлять опыт и эмоцию, которых автор не сообщал.",
        "Не додавати досвід та емоцію, яких автор не повідомляв.",
    ),
    pattern(
        "S11", (), "P2", "automatic-cta",
        r"\b(?:сохраните этот пост|сохрани этот пост|подпишитесь,? чтобы не пропустить|"
        r"пишите в комментариях|збережіть цей допис|збережи цей допис|"
        r"підпишіться,? щоб не пропустити|пишіть у коментарях)\b",
        "Шаблонный призыв к действию", "Шаблонний заклик до дії",
        "CTA выглядит добавленным автоматически, если не связан с целью поста.",
        "CTA виглядає доданим автоматично, якщо не пов’язаний із метою допису.",
        "Оставить только по задаче автора и сформулировать в его голосе.",
        "Лишити лише за завданням автора й сформулювати його голосом.",
    ),
    pattern(
        "S12", (), "P2", "transition-repeat",
        r"\b(?:кроме того|более того|таким образом|следовательно|"
        r"крім того|ба більше|таким чином|отже)\b",
        "Повтор шаблонных переходов", "Повтор шаблонних переходів",
        "Несколько одинаковых мостиков делают ход мысли механическим.",
        "Кілька однакових містків роблять хід думки механічним.",
        "Убрать лишние переходы или починить смысловую связь.",
        "Прибрати зайві переходи або полагодити змістовий зв’язок.",
        2,
    ),
    pattern(
        "S13", (), "P2", "contrast-slogan",
        r"\b(?:это|це)\s+не\s+просто\b[^.!?…]{0,100}[—–-]?\s*(?:это|це)\b",
        "Повтор конструкции «не просто X — это Y»", "Повтор конструкції «не просто X — це Y»",
        "Контраст используется как универсальный усилитель.",
        "Контраст використано як універсальний підсилювач.",
        "Оставить только реальное противопоставление.",
        "Лишити тільки справжнє протиставлення.",
        2,
    ),
    pattern(
        "S14", (), "P2", "question-hook",
        r"\b(?:в ч[её]м секрет\??|но вот в ч[её]м дело|почему это важно\??|"
        r"у чому секрет\??|але ось у чому річ|чому це важливо\??)\b",
        "Серия готовых вопросных крючков", "Серія готових питальних гачків",
        "Повтор вопрос–ответ выглядит как формула вовлечения.",
        "Повтор запитання–відповідь виглядає як формула залучення.",
        "Один настоящий вопрос оставить, остальные сформулировать прямо.",
        "Одне справжнє запитання лишити, решту сформулювати прямо.",
        2,
    ),
    pattern(
        "S15", (), "P2", "hedging-cluster",
        r"\b(?:может стать|способ(?:ен|на|но|ны)|призван[аоы]?|возможно,? может|"
        r"може стати|здатн(?:ий|а|е|і)|покликан(?:ий|а|е|і)|ймовірно,? може)\b",
        "Скопление неопределённых обещаний", "Скупчення невизначених обіцянок",
        "Повтор модальных форм скрывает степень уверенности.",
        "Повтор модальних форм приховує ступінь упевненості.",
        "Указать, что известно и что не проверено; не усиливать факт.",
        "Указати, що відомо й що не перевірено; не посилювати факт.",
        3,
    ),
    pattern(
        "S16", (), "P2", "hashtag-stuffing",
        r"(?:#[\wА-Яа-яЁёІіЇїЄєҐґ]+[\s,]*){6,}",
        "Перегруз хештегами", "Перевантаження хештегами",
        "Длинный автоматический хвост редко связан с голосом автора.",
        "Довгий автоматичний хвіст рідко пов’язаний із голосом автора.",
        "Оставить только заданные или действительно нужные хештеги.",
        "Лишити тільки задані або справді потрібні хештеги.",
    ),
    pattern(
        "R01", ("ru",), "P2", "ru-bureaucratese",
        r"\bданн(?:ый|ая|ое|ые|ого|ой|ому|ым|ом|ую|ых|ыми)\b",
        "«Данный» в обычном посте", "«Данный» у звичайному дописі",
        "Слово часто создаёт ненужную официальную дистанцию.",
        "Слово часто створює зайву офіційну дистанцію.",
        "Проверить замену на «этот» или назвать предмет.",
        "Перевірити заміну на «цей» або назвати предмет.",
    ),
    pattern(
        "R02", ("ru",), "P1", "ru-bureaucratese",
        r"\b(?:в рамках|на текущий момент|с целью|в части вопроса|в контексте вышеизложенного)\b",
        "Канцелярская рамка", "Канцелярська рамка",
        "Служебный оборот утяжеляет социальный пост.",
        "Службовий зворот обтяжує допис.",
        "Заменить на «сейчас», «чтобы», конкретный проект или удалить.",
        "Замінити на «зараз», «щоб», конкретний проєкт або видалити.",
    ),
    pattern(
        "R03", ("ru",), "P1", "ru-nominalization",
        r"\b(?:осуществ(?:ить|лять|ляет|ляется|ляются)|произвести|провести)\s+"
        r"(?:проведение|осуществление|анализ|оценк\w*|оптимизац\w*|реализац\w*)\b",
        "Действие спрятано в существительном", "Дію сховано в іменнику",
        "Связка из служебного глагола и существительного звучит тяжело.",
        "Сполука зі службового дієслова та іменника звучить важко.",
        "Вернуть один точный глагол: «проанализировать», «оценить» и т. п.",
        "Повернути одне точне дієслово.",
    ),
    pattern(
        "R04", ("ru",), "P2", "ru-copula",
        r"\bявля(?:ется|ются|лся|лась|лось|лись)\b",
        "Связка «является»", "Зв’язка «является»",
        "В бытовом посте связка часто раздувает простую мысль.",
        "У побутовому дописі зв’язка часто роздуває просту думку.",
        "Упростить, но сохранить в точном определении, если она нужна.",
        "Спростити, але зберегти в точному визначенні, якщо вона потрібна.",
    ),
    pattern(
        "R05", ("ru",), "P1", "ru-bureaucratese",
        r"\b(?:имеет место быть|имеет место|наблюдается (?:рост|снижение|увеличение)|"
        r"было принято решение)\b",
        "Безличная канцелярская конструкция", "Безособова канцелярська конструкція",
        "Непонятно, кто действует.", "Незрозуміло, хто діє.",
        "Назвать действующее лицо, если оно известно.",
        "Назвати виконавця, якщо він відомий.",
    ),
    pattern(
        "R06", ("ru",), "P1", "ru-calque",
        r"\b(?:разблокировать потенциал|бесшовн(?:ый|ая|ое|ые) (?:опыт|интеграция|переход)|"
        r"широкий спектр возможностей|комплексный подход)\b",
        "Готовая рекламная формула", "Готова рекламна формула",
        "Формула не называет конкретную пользу.", "Формула не називає конкретної користі.",
        "Заменить действием или результатом из исходника.",
        "Замінити дією або результатом із джерела.",
    ),
    pattern(
        "R07", ("ru",), "P1", "ru-meta",
        r"\b(?:давайте разбер[её]мся|рассмотрим подробнее|перейд[её]м к следующему|"
        r"важно понимать)\b",
        "Метатекст вместо мысли", "Метатекст замість думки",
        "Фраза анонсирует действие вместо самого действия.",
        "Фраза анонсує дію замість самої дії.",
        "Начать с тезиса или разбора.", "Почати з тези або розбору.",
    ),
    pattern(
        "U01", ("uk",), "P2", "uk-bureaucratese",
        r"\bдан(?:ий|а|е|і|ого|ій|ому|им|у|их|ими)\b",
        "«Даний» в обычном посте", "«Даний» у звичайному дописі",
        "В обычном посте слово часто создаёт официальную дистанцию.",
        "У звичайному дописі слово часто створює офіційну дистанцію.",
        "Проверить замену на «цей/ця/це».", "Перевірити заміну на «цей/ця/це».",
    ),
    pattern(
        "U02", ("uk",), "P1", "uk-bureaucratese",
        r"\b(?:на даний момент|у рамках|з метою здійснення|необхідно наголосити)\b",
        "Канцелярська рамка", "Канцелярська рамка",
        "Службовий зворот обтяжує допис.", "Службовий зворот обтяжує допис.",
        "Замінити на «зараз», «у межах», «щоб» або видалити.",
        "Замінити на «зараз», «у межах», «щоб» або видалити.",
    ),
    pattern(
        "U03", ("uk",), "P1", "uk-calque",
        r"\bприйм\w*\s+участь\b",
        "Калька «приймати участь»", "Калька «приймати участь»",
        "В украинском нормативная конструкция — «брати участь».",
        "Нормативна українська конструкція — «брати участь».",
        "Заменить на форму «брати участь» по времени и лицу.",
        "Замінити на відповідну форму «брати участь».",
    ),
    pattern(
        "U04", ("uk",), "P1", "uk-calque",
        r"\bявля(?:ється|ються|вся|лася|лося|лися)\b",
        "«Являється» как связка", "«Являється» як зв’язка",
        "Это частая калька, но у глагола есть прямое значение.",
        "Це поширена калька, але дієслово має пряме значення.",
        "В роли связки заменить на «є» или убрать; прямое значение сохранить.",
        "У ролі зв’язки замінити на «є» або прибрати; пряме значення зберегти.",
    ),
    pattern(
        "U05", ("uk",), "P1", "uk-calque",
        r"\bзаключа(?:ється|ються|вся|лася|лося|лися)\s+(?:в|у)\b",
        "Калька «заключається в»", "Калька «заключається в»",
        "Нужное значение передаёт «полягає в».", "Потрібне значення передає «полягає в».",
        "Заменить на «полягає в/у».", "Замінити на «полягає в/у».",
    ),
    pattern(
        "U06", ("uk",), "P1", "uk-calque",
        r"\bпо відношенню до\b",
        "Калька «по відношенню до»", "Калька «по відношенню до»",
        "Украинская конструкция зависит от смысла.", "Українська конструкція залежить від змісту.",
        "Выбрать «щодо», «стосовно» или «порівняно з».",
        "Обрати «щодо», «стосовно» або «порівняно з».",
    ),
    pattern(
        "U07", ("uk",), "P2", "uk-calque",
        r"\bна протязі\b",
        "«На протязі» о времени", "«На протязі» про час",
        "Для длительности нужно «протягом»; прямое значение сквозняка допустимо.",
        "Для тривалості потрібне «протягом»; пряме значення протягу допустиме.",
        "Проверить контекст и при времени заменить на «протягом».",
        "Перевірити контекст і для часу замінити на «протягом».",
    ),
    pattern(
        "U08", ("uk",), "P1", "uk-calque",
        r"\bслідуюч(?:ий|а|е|і|ого|ій|ому|им|у|их|ими)\b",
        "Калька «слідуючий»", "Калька «слідуючий»",
        "В значении очередности нормативно «наступний».",
        "У значенні черговості нормативно «наступний».",
        "Заменить на нужную форму «наступний».",
        "Замінити на потрібну форму «наступний».",
    ),
    pattern(
        "U09", ("uk",), "P2", "uk-calque",
        r"\bвірн(?:ий|а|е|і|ого|ій|ому|им|у|их|ими)\s+(?:рішення|відповідь|варіант|метод|підхід)\b",
        "«Вірний» в значении правильности", "«Вірний» у значенні правильності",
        "Для правильности обычно нужно «правильний»; «вірний друг» корректно.",
        "Для правильності зазвичай потрібно «правильний»; «вірний друг» правильно.",
        "Проверить замену на «правильний».", "Перевірити заміну на «правильний».",
    ),
    pattern(
        "U10", ("uk",), "P2", "uk-calque",
        r"\bна рахунок\b",
        "«На рахунок» в значении темы", "«На рахунок» у значенні теми",
        "Оборот корректен для банковского счёта, но не для темы разговора.",
        "Зворот правильний для банківського рахунку, але не для теми розмови.",
        "В значении темы заменить на «про», «щодо» или «стосовно».",
        "У значенні теми замінити на «про», «щодо» або «стосовно».",
    ),
    pattern(
        "U11", ("uk",), "P1", "uk-calque",
        r"\bприйм\w*\s+до уваги\b",
        "Калька «приймати до уваги»", "Калька «приймати до уваги»",
        "Естественные варианты — «брати до уваги» или «враховувати».",
        "Природні варіанти — «брати до уваги» або «враховувати».",
        "Выбрать вариант по контексту.", "Обрати варіант за контекстом.",
    ),
    pattern(
        "U12", ("uk",), "P2", "uk-calque",
        r"\b(?:по причині|по мірі|по можливості)\b",
        "Прийменникова калька", "Прийменникова калька",
        "Механический `по` часто переносит русскую конструкцию.",
        "Механічне `по` часто переносить російську конструкцію.",
        "По смыслу выбрать «через/з причини», «у міру», «за можливості».",
        "За змістом обрати «через/з причини», «у міру», «за можливості».",
    ),
    pattern(
        "U13", ("uk",), "P2", "uk-word-choice",
        r"\b(?:співпада(?:є|ють|ти|в|ла|ло|ли)|протиріччя|задавати\s+(?:питання|запитання))\b",
        "Контекстный русизм", "Контекстний росіянізм",
        "В нейтральном тексте часто есть естественнее: «збігатися», «суперечність», «ставити запитання».",
        "У нейтральному тексті часто природніше: «збігатися», «суперечність», «ставити запитання».",
        "Проверить норму, регистр и голос; не заменять механически.",
        "Перевірити норму, регістр і голос; не замінювати механічно.",
    ),
)


def configure_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def detect_language(text: str) -> str:
    lowered = text.lower()
    ru_unique = sum(lowered.count(char) for char in "ыэёъ")
    uk_unique = sum(lowered.count(char) for char in "іїєґ")
    tokens = [token.lower() for token in words(text)]
    ru_markers = {"что", "это", "как", "но", "или", "уже", "ещё", "если", "который", "чтобы", "мы", "вы", "он", "она"}
    uk_markers = {"що", "це", "як", "але", "або", "вже", "ще", "якщо", "який", "щоб", "ми", "ви", "він", "вона"}
    ru_score = sum(token in ru_markers for token in tokens)
    uk_score = sum(token in uk_markers for token in tokens)

    if ru_unique and uk_unique:
        if (ru_unique >= 2 and uk_unique >= 2) or (ru_score >= 2 and uk_score >= 2):
            return "mixed"
        if ru_score >= uk_score + 2:
            return "ru"
        if uk_score >= ru_score + 2:
            return "uk"
        return "mixed"
    if ru_unique:
        return "ru"
    if uk_unique:
        return "uk"

    if ru_score >= uk_score + 2:
        return "ru"
    if uk_score >= ru_score + 2:
        return "uk"
    return "unknown"


def preferred_language(detected: str, pattern_languages: Sequence[str] = ()) -> str:
    if detected == "uk" or (detected == "mixed" and pattern_languages == ("uk",)):
        return "uk"
    return "ru"


def active_pattern(item: Pattern, detected: str) -> bool:
    if not item.languages:
        return True
    if detected == "mixed":
        return True
    return detected in item.languages


def snippet(text: str, start: int, end: int, radius: int = 42) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    value = re.sub(r"\s+", " ", text[left:right]).strip()
    if left:
        value = "…" + value
    if right < len(text):
        value += "…"
    return value


def mask_markdown_code(text: str) -> str:
    """Mask Markdown code and non-prose lines while preserving character offsets."""
    chars = list(text)
    ranges: list[tuple[int, int]] = []
    ranges.extend((match.start(), match.end()) for match in re.finditer(r"```.*?```", text, re.DOTALL))
    ranges.extend((match.start(), match.end()) for match in re.finditer(r"`[^`\n]+`", text))
    ranges.extend((match.start(), match.end()) for match in re.finditer(r"^\s*#{1,6}\s+.*$", text, re.MULTILINE))
    ranges.extend(
        (match.start(), match.end())
        for match in re.finditer(r"^\s*\[[^\]]+\]\([^)]+\)\s*$", text, re.MULTILINE)
    )
    for start, end in ranges:
        for index in range(start, end):
            if chars[index] not in "\r\n":
                chars[index] = " "
    return "".join(chars)


def finding_from_pattern(item: Pattern, matches: Sequence[re.Match[str]], text: str, detected: str) -> dict:
    lang = preferred_language(detected, item.languages)
    evidence: list[str] = []
    for match in matches:
        value = snippet(text, match.start(), match.end())
        if value not in evidence:
            evidence.append(value)
        if len(evidence) == 3:
            break
    return {
        "code": item.code,
        "severity": item.severity,
        "category": item.category,
        "title": item.title_uk if lang == "uk" else item.title_ru,
        "why": item.why_uk if lang == "uk" else item.why_ru,
        "fix": item.fix_uk if lang == "uk" else item.fix_ru,
        "count": len(matches),
        "evidence": evidence,
    }


def sentence_list(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip() and words(part)]


def localized_finding(
    detected: str,
    code: str,
    severity: str,
    category: str,
    title_ru: str,
    title_uk: str,
    why_ru: str,
    why_uk: str,
    fix_ru: str,
    fix_uk: str,
    evidence: Iterable[str],
    count: int,
) -> dict:
    lang = preferred_language(detected)
    return {
        "code": code,
        "severity": severity,
        "category": category,
        "title": title_uk if lang == "uk" else title_ru,
        "why": why_uk if lang == "uk" else why_ru,
        "fix": fix_uk if lang == "uk" else fix_ru,
        "count": count,
        "evidence": list(evidence),
    }


def structural_findings(text: str, detected: str) -> list[dict]:
    findings: list[dict] = []
    sentences = sentence_list(text)
    lengths = [len(words(sentence)) for sentence in sentences]

    if len(lengths) >= 6 and statistics.mean(lengths) >= 6:
        mean = statistics.mean(lengths)
        coefficient = statistics.pstdev(lengths) / mean if mean else math.inf
        if coefficient < 0.22:
            findings.append(localized_finding(
                detected, "T01", "P2", "uniform-rhythm",
                "Почти одинаковая длина предложений", "Майже однакова довжина речень",
                "Длинный фрагмент идёт в одном ритме.", "Довгий фрагмент іде в одному ритмі.",
                "Менять длину только там, где меняется функция предложения.",
                "Змінювати довжину лише там, де змінюється функція речення.",
                [f"lengths={lengths[:12]}, variation={coefficient:.2f}"], 1,
            ))

    longest_short_streak = 0
    current_streak = 0
    for length in lengths:
        if 0 < length <= 4:
            current_streak += 1
            longest_short_streak = max(longest_short_streak, current_streak)
        else:
            current_streak = 0
    if longest_short_streak >= 3:
        short_examples = [sentence for sentence, length in zip(sentences, lengths) if length <= 4][:3]
        findings.append(localized_finding(
            detected, "T02", "P2", "fragment-streak",
            "Серия нарочито коротких фраз", "Серія навмисно коротких фраз",
            "Три и более обрыва подряд могут имитировать драматичность.",
            "Три або більше уривків поспіль можуть імітувати драматичність.",
            "Соединить фразы, если такой ритм не подтверждён голосом автора.",
            "Об’єднати фрази, якщо такий ритм не підтверджений голосом автора.",
            short_examples, longest_short_streak,
        ))

    nonempty_lines = [line for line in text.splitlines() if line.strip()]
    bullet_re = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
    bullets = [line.strip() for line in nonempty_lines if bullet_re.match(line)]
    if len(bullets) >= 5 and len(bullets) / max(len(nonempty_lines), 1) >= 0.45:
        findings.append(localized_finding(
            detected, "T03", "P2", "list-overuse",
            "Большая часть поста превращена в список", "Більшу частину допису перетворено на список",
            "Связное рассуждение может выглядеть как шаблон карточек.",
            "Зв’язне міркування може виглядати як шаблон карток.",
            "Оставить список только для самостоятельных пунктов или шагов.",
            "Лишити список тільки для самостійних пунктів або кроків.",
            bullets[:3], len(bullets),
        ))

    emoji_re = re.compile(r"^\s*[\U0001F300-\U0001FAFF\u2600-\u27BF]\ufe0f?\s*")
    emoji_lines = [line.strip() for line in nonempty_lines if emoji_re.match(line)]
    if len(emoji_lines) >= 3:
        findings.append(localized_finding(
            detected, "T04", "P2", "decorative-emoji",
            "Эмодзи как повторяющийся маркер пунктов", "Емодзі як повторюваний маркер пунктів",
            "Одинаковый декор формирует механический скелет.",
            "Однаковий декор формує механічний скелет.",
            "Оставить эмодзи с функцией или в устойчивом голосе автора.",
            "Лишити емодзі з функцією або в усталеному голосі автора.",
            emoji_lines[:3], len(emoji_lines),
        ))

    bold_spans = re.findall(r"\*\*[^*\n]+\*\*", text)
    if len(bold_spans) >= 4:
        findings.append(localized_finding(
            detected, "T05", "P2", "bold-overuse",
            "Слишком много жирных акцентов", "Забагато жирних акцентів",
            "Когда выделено всё, навигация перестаёт работать.",
            "Коли виділено все, навігація перестає працювати.",
            "Оставить только функциональные акценты.", "Лишити тільки функціональні акценти.",
            bold_spans[:3], len(bold_spans),
        ))

    openers: dict[str, list[str]] = {}
    for sentence in sentences:
        tokens = [token.lower() for token in words(sentence)]
        if len(tokens) >= 2:
            opener = " ".join(tokens[:2])
            openers.setdefault(opener, []).append(sentence)
    repeated = [(opener, items) for opener, items in openers.items() if len(items) >= 3]
    if repeated:
        opener, items = max(repeated, key=lambda entry: len(entry[1]))
        findings.append(localized_finding(
            detected, "T06", "P2", "repeated-openers",
            "Одинаковые зачины предложений", "Однакові початки речень",
            "Три одинаковых старта подряд или в одном блоке создают шаблон.",
            "Три однакові початки поспіль або в одному блоці створюють шаблон.",
            "Перестроить только повторяющиеся зачины, сохранив смысл.",
            "Перебудувати лише повторювані початки, зберігши зміст.",
            [f"{opener}: {snippet(item, 0, min(len(item), 55), 0)}" for item in items[:3]], len(items),
        ))

    return findings


def audit(text: str, language: str = "auto") -> dict:
    if language not in {"auto", "ru", "uk", "mixed"}:
        raise ValueError(f"Unsupported language: {language}")
    scan_text = mask_markdown_code(text)
    detected = detect_language(scan_text) if language == "auto" else language
    findings: list[dict] = []

    for item in PATTERNS:
        if not active_pattern(item, detected):
            continue
        matches = list(re.finditer(item.regex, scan_text, flags=re.IGNORECASE | re.MULTILINE))
        if len(matches) >= item.min_count:
            findings.append(finding_from_pattern(item, matches, text, detected))

    findings.extend(structural_findings(scan_text, detected))
    findings.sort(key=lambda item: (SEVERITY_ORDER[item["severity"]], item["code"]))
    counts = {severity: sum(item["severity"] == severity for item in findings) for severity in ("P0", "P1", "P2")}

    return {
        "language": detected,
        "word_count": len(words(text)),
        "sentence_count": len(sentence_list(text)),
        "finding_counts": counts,
        "findings": findings,
        "disclaimer": (
            "Редакторские сигналы, не вывод об авторстве."
            if detected != "uk"
            else "Редакторські сигнали, а не висновок про авторство."
        ),
    }


def read_text(path_value: str) -> str:
    if path_value == "-":
        return sys.stdin.read()

    raw = Path(path_value).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"Cannot decode {path_value} as UTF-8 or Windows-1251")


def render_text(result: dict) -> str:
    ukrainian = result["language"] == "uk"
    language_names = {
        "ru": "русский",
        "uk": "українська",
        "mixed": "смешанный ru/uk",
        "unknown": "не определён",
    }
    lines = [
        ("Мова" if ukrainian else "Язык") + f": {language_names[result['language']]}",
        ("Слів" if ukrainian else "Слов") + f": {result['word_count']}",
        ("Речень" if ukrainian else "Предложений") + f": {result['sentence_count']}",
        f"P0: {result['finding_counts']['P0']} | P1: {result['finding_counts']['P1']} | P2: {result['finding_counts']['P2']}",
        "",
    ]

    if not result["findings"]:
        lines.append(
            "Суттєвих редакторських патернів не знайдено."
            if ukrainian
            else "Существенных редакторских паттернов не найдено."
        )
    else:
        for item in result["findings"]:
            lines.append(f"[{item['severity']}] {item['code']} — {item['title']} (x{item['count']})")
            for evidence in item["evidence"]:
                lines.append(f"  «{evidence}»")
            lines.append(f"  {item['why']}")
            lines.append(f"  → {item['fix']}")
            lines.append("")

    lines.append(result["disclaimer"])
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit Russian/Ukrainian social text for editorial patterns; never classifies authorship."
    )
    parser.add_argument("path", nargs="?", default="-", help="UTF-8/CP1251 text file, or - for stdin")
    parser.add_argument("--lang", choices=("auto", "ru", "uk", "mixed"), default="auto")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8()
    args = build_parser().parse_args(argv)
    try:
        text = read_text(args.path)
    except (OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = audit(text, args.lang)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
