import asyncio
import base64
from io import BytesIO
import aiocron
import sqlite3
from playwright.async_api import async_playwright
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile
from config import *
from utils import *

bot = Bot(TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

latest_news_links = set()
conn = sqlite3.connect('news.db')
cursor = conn.cursor()

cursor.execute('''
  CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    link TEXT UNIQUE,
    img TEXT,
    date TEXT,
    hashtag TEXT,
    sent INTEGER DEFAULT 0
  )
''')
conn.commit()

news_sites = [
  'https://treknews.net/category/news/',
  'https://www.dailystartreknews.com/',
  # 'https://www.startrek.com/en-un/category/news',
  # 'https://trekmovie.com/',
  # 'https://blog.trekcore.com/'
]

async def send_base64_image(img_str, caption):
  """Отправляет изображение в формате base64 в Telegram"""
  header, data = img_str.split(',', 1)
  image_data = base64.b64decode(data)
  image_file = BytesIO(image_data)
  image = FSInputFile(image_file, filename='image.png')
  await send_photo_with_retry(image, caption)

async def send_image_url(img_url, caption):
  """Отправляет изображение по URL в Telegram"""
  await send_photo_with_retry(img_url, caption)

async def send_photo_with_retry(photo, caption, retries=3, delay=10):
  """Отправка фото с повторными попытками при ошибке подключения и тайм-аутом"""
  for attempt in range(retries):
    try:
      await bot.send_photo(
        chat_id=CHANNEL_ID,
        photo=photo,
        caption=caption,
        parse_mode="HTML"
      )
      print("Успешно отправлено!")
      await asyncio.sleep(delay)  # Пауза после успешной отправки
      break  # Если отправка прошла успешно, выходим из цикла
    except Exception as e:
      print(f"Ошибка при отправке: {e}. Попытка {attempt + 1} из {retries}.")
      await asyncio.sleep(5)  # Задержка перед повторной попыткой

async def fetch_news(first_run=False):
  async with async_playwright() as p:
    browser = await p.chromium.launch(headless=False)
    context = await browser.new_context()

    # Обходим каждый сайт в списке
    for site in news_sites:
      page = await context.new_page()  # Открываем новую страницу в контексте
      print(f"Открываем сайт: {site}")

      try:
        await page.goto(site, timeout=60000)  # Тайм-аут 60 секунд
        print(f"Сайт {site} загружен успешно.")
        # Обрабатываем страницы в зависимости от структуры сайта
        if 'treknews.net' in site:
          await process_treknews(page, first_run=True)
        elif 'dailystartreknews.com' in site:
          await process_dailystartreknews(page)
        # elif 'startrek.com' in site:
        #     await process_startrek(page)
        # elif 'trekmovie.com' in site:
        #     await process_trekmovie(page)
        # elif 'trekcore.com' in site:
        #     await process_trekcore(page)
      except TimeoutError:
        print(f"Загрузка сайта {site} завершилась по тайм-ауту.")
      except Exception as e:
        print(f"Ошибка при загрузке сайта {site}: {e}")

    await browser.close()

async def process_treknews(page, first_run=False):
  await scroll_to_bottom(page)
  
  # Парсим новости и добавляем их в базу данных
  news_items = await page.query_selector_all('article.infinite-post')

  for item in news_items:
    title_element = await item.query_selector('.zox-art-title .zox-s-title2')
    link_element = await item.query_selector('.zox-art-img a')
    img_element = await item.query_selector('.zox-art-img img[width="600"][height="337"]')
    hashtag_element = await item.query_selector('span.zox-s-cat')

    if title_element and link_element and img_element and hashtag_element:
      title = await title_element.inner_text()
      link = await link_element.get_attribute('href')
      img = await img_element.get_attribute('src')
      hashtag = await hashtag_element.inner_html()
      date = extract_and_format_date(link)

      cursor.execute("SELECT link FROM news WHERE link = ?", (link,))
      if cursor.fetchone() is None:
        if is_valid_image(img):
          cursor.execute("INSERT INTO news (title, link, img, date, hashtag, sent) VALUES (?, ?, ?, ?, ?, 0)",
            (title, link, img, date, hashtag))
          conn.commit()

  # Извлекаем новости из базы данных
  await send_news_from_db(first_run)

async def send_news_from_db(first_run=False):
  """Отправляет новости, хранящиеся в базе данных, в Telegram"""
  if first_run:
    # Если это первый запуск, отправляем только последние 7 новостей
    cursor.execute("SELECT id, title, link, img, date, hashtag FROM news DESC LIMIT 7")
    news_list = cursor.fetchall()
    news_list.reverse()  # Отправляем сначала старые, затем новые
  else:
    cursor.execute("SELECT id, title, link, img, date, hashtag FROM news WHERE sent = 0")
    news_list = cursor.fetchall()

  for news_item in news_list:
    news_id, title, link, img, date, hashtag = news_item
    caption = f'''
      #{hashtag}

      Date: {date}

      {title}
      Full article: {link}
    '''
    if is_base64_image(img):
      await send_base64_image(img, caption)
    else:
      await send_image_url(img, caption)
    
    # Помечаем запись как отправленную
    cursor.execute("UPDATE news SET sent = 1 WHERE id = ?", (news_id,))
    conn.commit()

  # Если это первый запуск, помечаем оставшиеся записи как отправленные
  if first_run:
    cursor.execute("UPDATE news SET sent = 1 WHERE sent = 0")
    conn.commit()

async def process_dailystartreknews(page):
  pass

async def process_startrek(page):
  pass

async def process_trekmovie(page):
  pass

async def process_trekcore(page):
  pass

aiocron.crontab('* * * * *', func=fetch_news)

async def main():
  await fetch_news(first_run=True)
  await dp.start_polling(bot)

if __name__ == '__main__':
  asyncio.run(main())