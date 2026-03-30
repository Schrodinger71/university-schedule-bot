import disnake
import os
import json
import aiohttp
from datetime import datetime, timedelta, time
import zoneinfo
from aiohttp import ClientTimeout
from disnake.ext import tasks
from disnake.ext import commands

# ====================== НАСТРОЙКИ ======================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
USER_ID = int(os.getenv("USER_ID"))
GROUP_INT = os.getenv("GROUP_INT")

URL = f"https://tulsu.ru/schedule/queries/GetSchedule.php?search_field=GROUP_P&search_value={GROUP_INT}"
CACHE_FILE = "/app/data/schedule_cache.json"
# ======================================================
intents = disnake.Intents.all()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(intents=intents)


def save_cache(data):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка чтения кэша: {e}")
    return None


async def fetch_schedule():
    timeout = ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(URL) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    save_cache(data)
                    print("✅ Расписание успешно загружено и сохранено в кэш")
                    return data
                else:
                    print(f"HTTP ошибка: {resp.status}")
                    return None
    except Exception as e:
        print(f"Ошибка запроса к сайту: {e}")
        return None


def get_today_lessons(data):
    if not data or not isinstance(data, list):
        return []
    tz = zoneinfo.ZoneInfo("Europe/Moscow")
    today = datetime.now(tz).strftime("%d.%m.%Y")
    return [lesson for lesson in data if lesson.get("DATE_Z") == today]


def get_lessons_range(data, start_date: str, end_date: str):
    if not data or not isinstance(data, list):
        return {}

    lessons_by_day = {}

    start = datetime.strptime(start_date, "%d.%m.%Y")
    end = datetime.strptime(end_date, "%d.%m.%Y")

    for lesson in data:
        date_z = lesson.get("DATE_Z")
        if not date_z:
            continue

        try:
            lesson_date = datetime.strptime(date_z, "%d.%m.%Y")
        except:
            continue

        if start <= lesson_date <= end:
            if date_z not in lessons_by_day:
                lessons_by_day[date_z] = []
            lessons_by_day[date_z].append(lesson)

    return lessons_by_day


def create_embed(lessons, date_str: str, cache_note: str = ""):
    color = 0xffa500 if cache_note else 0x00ff00
    embed = disnake.Embed(
        title=f"📅 Расписание на {date_str}",
        description=cache_note or None,
        color=color,
    )

    if not lessons:
        embed.add_field(name="Сегодня пар нет!", value="Можно отдохнуть 🎉", inline=False)
        return embed

    for i, lesson in enumerate(lessons, 1):
        field_value = (
            f"**{lesson.get('TIME_Z', 'N/A')}** — {lesson.get('KOW', 'N/A')}\n"
            f"{lesson.get('DISCIP', 'N/A')}\n"
            f"**Аудитория:** {lesson.get('AUD', 'N/A')}\n"
            f"**Преподаватель:** {lesson.get('PREP', 'N/A')}"
        )
        embed.add_field(name=f"Пара №{i}", value=field_value, inline=False)
    return embed


async def send_daily():
    tz = zoneinfo.ZoneInfo("Europe/Moscow")
    today_str = datetime.now(tz).strftime("%d.%m.%Y")

    fetched = await fetch_schedule()
    if fetched is not None:
        data = fetched
        cache_note = ""
    else:
        data = load_cache()
        cache_note = "⚠️ Данные из кэша (сайт временно недоступен)"

    if data is None:
        embed = disnake.Embed(title="❌ Ошибка", description="Не удалось получить расписание.\nКэш пуст.", color=0xff0000)
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            await channel.send(f"<@{USER_ID}>", embed=embed)
        return

    lessons = get_today_lessons(data)
    embed = create_embed(lessons, today_str, cache_note)

    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(f"<@{USER_ID}>", embed=embed)
    else:
        print("Канал не найден!")


@bot.slash_command(name="расписание", description="Получить расписание на сегодня")
async def cmd_schedule(inter: disnake.ApplicationCommandInteraction):
    await inter.response.defer()

    tz = zoneinfo.ZoneInfo("Europe/Moscow")
    today_str = datetime.now(tz).strftime("%d.%m.%Y")

    fetched = await fetch_schedule()
    if fetched is not None:
        data = fetched
        cache_note = ""
    else:
        data = load_cache()
        cache_note = "⚠️ Данные из кэша"

    if data is None:
        await inter.edit_original_response("Не удалось получить расписание.")
        return

    lessons = get_today_lessons(data)
    embed = create_embed(lessons, today_str, cache_note)
    await inter.edit_original_response(embed=embed)


@bot.slash_command(name="расписание_неделя", description="Получить расписание на ближайшие 7 дней")
async def cmd_week_schedule(inter: disnake.ApplicationCommandInteraction):
    await inter.response.defer()

    fetched = await fetch_schedule()
    if fetched is not None:
        data = fetched
        cache_note = ""
    else:
        data = load_cache()
        cache_note = "⚠️ Данные из кэша"

    if data is None:
        await inter.edit_original_response("Не удалось получить расписание.")
        return

    tz = zoneinfo.ZoneInfo("Europe/Moscow")
    now = datetime.now(tz)

    dates = [(now + timedelta(days=i)).strftime("%d.%m.%Y") for i in range(7)]
    start_date = dates[0]
    end_date = dates[-1]

    lessons_by_day = get_lessons_range(data, start_date, end_date)

    header = disnake.Embed(
        title=f"📅 Расписание на неделю ({start_date} — {end_date})",
        description=cache_note or None,
        color=0xffa500 if cache_note else 0x00ff00,
    )

    embeds = [header]

    for date_str in sorted(lessons_by_day.keys()):
        day_lessons = lessons_by_day[date_str]
        if day_lessons:
            day_embed = create_embed(day_lessons, date_str, cache_note="")
            embeds.append(day_embed)

    if len(embeds) == 1:
        no_lessons = disnake.Embed(
            title="🎉 На ближайшую неделю пар нет!",
            description="Полный отдых! Отличная возможность выспаться 😴",
            color=0x00ff00,
        )
        await inter.edit_original_response(embed=no_lessons)
        return

    await inter.edit_original_response(embeds=embeds[:10])


# ====================== ЕЖЕДНЕВНЫЙ ТАСК (6:00 МСК) ======================
@tasks.loop(time=time(hour=6, minute=0, tzinfo=zoneinfo.ZoneInfo("Europe/Moscow")))
async def daily_task():
    await send_daily()


@bot.event
async def on_ready():
    print(f"✅ Бот {bot.user} успешно запущен!")

    if not daily_task.is_running():
        daily_task.start()

    tz = zoneinfo.ZoneInfo("Europe/Moscow")
    now = datetime.now(tz)

    if now.hour >= 6:
        await send_daily()


if __name__ == "__main__":
    if not DISCORD_TOKEN or not CHANNEL_ID or not USER_ID:
        raise ValueError("❌ Необходимо установить DISCORD_TOKEN, CHANNEL_ID и USER_ID в переменных окружения!")
    bot.run(DISCORD_TOKEN)
