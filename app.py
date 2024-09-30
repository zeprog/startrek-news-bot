import asyncio
import base64
import sqlite3
from dateutil import parser
from datetime import datetime
from io import BytesIO
from concurrent.futures import ProcessPoolExecutor
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
db_dir = '/app/db'
os.makedirs(db_dir, exist_ok=True)
db_path = os.path.join(db_dir, 'news.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    link TEXT UNIQUE,
    img TEXT,
    date TEXT,
    hashtag TEXT,
    sent INTEGER DEFAULT 0
  )''')
cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON news (date)")
conn.commit()

news_sites = [
  'https://treknews.net/category/news/',
  'https://www.dailystartreknews.com/',
  'https://www.startrek.com/en-un/category/news',
  'https://trekmovie.com/',
  'https://blog.trekcore.com/'
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
  await bot.send_photo(
    chat_id=CHANNEL_ID,
    photo=img_url,
    caption=caption,
    parse_mode="HTML"
  )

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

def format_date(date_str):
  try:
    date_obj = parser.parse(date_str)
    return date_obj.strftime("%Y-%m-%d") 
  except ValueError as e:
    print(f"Ошибка при парсинге даты: {date_str}. Ошибка: {e}")
    return date_str

async def fetch_news_from_site(site):
  news_list = []
  async with async_playwright() as p:
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto(site, timeout=60000)
    print(f"Обрабатываем сайт: {site}")

    if 'treknews.net' in site:
      news_list = await process_treknews(page)
    elif 'dailystartreknews.com' in site:
      news_list = await process_dailystartreknews(page)
    elif 'startrek.com' in site:
      news_list = await process_startrek(page)
    elif 'trekmovie.com' in site:
      news_list = await process_trekmovie(page)
    elif 'trekcore.com' in site:
      news_list = await process_trekcore(page)

    await context.close()
    await browser.close()
  print(f"Собрано новостей с {site}: {len(news_list)}")
  return news_list

def process_site(site):
  loop = asyncio.new_event_loop()
  asyncio.set_event_loop(loop)
  news_list = loop.run_until_complete(fetch_news_from_site(site))
  loop.close()
  return news_list

async def fetch_news():
  all_news = []

  with ProcessPoolExecutor() as executor:
    futures = {executor.submit(process_site, site): site for site in news_sites}
    
    for future in futures:
      news_list = future.result()
      all_news.extend(news_list)

  # Сортируем все новости по дате перед вставкой в базу
  all_news.sort(key=lambda x: datetime.strptime(x['date'], "%Y-%m-%d"))

  # Вставляем все собранные новости в базу данных за один раз
  for news in all_news:
    try:
      cursor.execute("INSERT INTO news (title, link, img, date, hashtag, sent) VALUES (?, ?, ?, ?, ?, 0)",
                      (news['title'], news['link'], news['img'], news['date'], news['hashtag']))
    except sqlite3.IntegrityError:
      print(f"Новость уже существует в базе: {news['link']}")

  conn.commit()
  print(f"Всего новостей собрано: {len(all_news)}")
  return all_news

async def send_news_from_db(first_run=False):
  # Получаем все неотправленные новости и сортируем их по дате
  cursor.execute("SELECT title, link, img, date, hashtag FROM news WHERE sent = 0 ORDER BY date ASC")
  news_list = cursor.fetchall()

  if first_run:
    news_list = news_list[-7:]  # Отправляем только последние 7 новостей, если это первый запуск

  for news_item in news_list:
    title, link, img, date, hashtag = news_item
    caption = f'''
    {hashtag}

    Date: {datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")}

    {title}

    Full article: {link}
    '''
    if is_base64_image(img):
      await send_base64_image(img, caption)
    else:
      await send_image_url(img, caption)

    # Обновляем статус отправки
    cursor.execute("UPDATE news SET sent = 1 WHERE link = ?", (link,))
    conn.commit()
    
    # Пауза между отправкой новостей (например, 10 секунд)
    await asyncio.sleep(10)

  # Если это первый запуск, помечаем все оставшиеся как отправленные
  if first_run:
    cursor.execute("UPDATE news SET sent = 1 WHERE sent = 0")
    conn.commit()

async def process_treknews(page):
  await scroll_to_bottom(page)
  news_items = await page.query_selector_all('article.infinite-post')
  news_list = []

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
      date = format_date(extract_and_format_date(link))  # Форматируем дату

      news_list.append({
        'title': title,
        'link': link,
        'img': img,
        'date': date,
        'hashtag': f'#{hashtag}'
      })

  return news_list

async def process_dailystartreknews(page):
  await scroll_to_bottom(page)
  news_items = await page.query_selector_all('.sqs-block-summary-v2 .summary-item.positioned')
  news_list = []

  for item in news_items:
    title_element = await item.query_selector('.summary-title')
    link_element = await item.query_selector('.summary-title a')
    img_element = await item.query_selector('.summary-thumbnail-image')
    hashtag_elements = await item.query_selector_all('.summary-metadata-item.summary-metadata-item--tags a')
    date_element = await item.query_selector('time.summary-metadata-item')

    if title_element and link_element and img_element and hashtag_elements and date_element:
      title = await title_element.inner_text()
      link = await link_element.get_attribute('href')
      img = await img_element.get_attribute('src')
      hashtags = ', '.join([await tag.inner_text() for tag in hashtag_elements])
      formatted_hashtags = f'#News {format_tags(hashtags)}'
      date = format_date(await date_element.get_attribute('datetime'))

      news_list.append({
        'title': title,
        'link': f'https://www.dailystartreknews.com{link}',
        'img': img,
        'date': date,
        'hashtag': formatted_hashtags
      })
    else:
      print("Не все элементы найдены для одной новости.")
      print(f"Title Element: {title_element}, Link Element: {link_element}, Img Element: {img_element}, Hashtag Elements: {hashtag_elements}, Date Element: {date_element}")

  return news_list

async def process_startrek(page):
  await scroll_to_bottom(page)
  news_items = await page.query_selector_all('.VerticalTeaser_verticalTeaser__5APa4.VerticalTeaser_page__CU6_R')
  news_list = []

  months = {
    'янв.': '01',
    'Jan': '01',
    'фев.': '02',
    'Feb': '02',
    'мар.': '03',
    'March': '03',
    'Mar': '03',
    'апр.': '04',
    'Apr': '04',
    'April': '04',
    'май': '05',
    'May': '05',
    'июн.': '06',
    'Jun': '06',
    'June': '06',
    'июл.': '07',
    'Jul': '07',
    'July': '07',
    'авг.': '08',
    'Aug': '08',
    'August': '08',
    'сен.': '09',
    'сент.': '09',
    'Sep': '09',
    'окт.': '10',
    'Oct': '10',
    'нояб.': '11',
    'Nov': '11',
    'дек.': '12',
    'Dec': '12'
  }

  for item in news_items:
    title_element = await item.query_selector('.VerticalTeaser_articleLinkTitle__8ihMI')
    link_element = title_element  # Используем тот же элемент для ссылки
    img_element = await item.query_selector('.VerticalTeaser_articleLinkImage__nBvv7 img')
    hashtag_element = await item.query_selector('.VerticalTeaser_eyebrow__iQe1e a')

    if title_element and link_element and img_element and hashtag_element:
      title = await title_element.inner_text()
      link = await link_element.get_attribute('href')
      img = await img_element.get_attribute('src')
      hashtag = await hashtag_element.inner_html()

      # Проверка наличия ссылки в базе данных
      cursor.execute("SELECT COUNT(*) FROM news WHERE link = ?", (link,))
      exists = cursor.fetchone()[0] > 0
      
      if not exists:  # Если ссылки нет в базе
        # Открываем новую вкладку
        new_page = await page.context.new_page()
        await new_page.goto(f'https://www.startrek.com{link}', timeout=120000)

        # Дождитесь загрузки нужного элемента на новой странице
        await new_page.wait_for_selector('.Article_deemphasized__Pb5VW.Article_publication__QjpzT.paragraph-light')
        date_element = await new_page.query_selector('.Article_deemphasized__Pb5VW.Article_publication__QjpzT.paragraph-light')
        
        if date_element:
          date_parts = await date_element.inner_text()
          date_parts = date_parts.split(' ')  # Разделяем по пробелам
          # Преобразуем дату в нужный формат
          # day = date_parts[1].zfill(2)  # Добавляем ведущий ноль
          day = date_parts[2].split(',')[0].zfill(2)  # Добавляем ведущий ноль
          month = months[date_parts[1]]
          year = date_parts[3].replace('г.', '').strip()  # Убираем "г."
          
          formatted_date = f"{year}-{month}-{day}"  # Форматируем в "гггг-мм-дд"
          
          news_list.append({
            'title': title,
            'link': f'https://www.startrek.com{link}',
            'img': img,
            'date': formatted_date,  # Используем отформатированную дату
            'hashtag': f'#{hashtag}'
          })
        else:
          print(f"Дата не найдена для статьи: {link}")

  return news_list

async def process_trekmovie(page):
  await scroll_to_bottom(page)
  news_items = await page.query_selector_all('.clearfix article')
  news_list = []

  for item in news_items:
    title_element = await item.query_selector('h3 a')
    link_element = title_element
    img_element = await item.query_selector('.content-thumb a img')
    hashtag_elements = await item.query_selector_all('.entry-meta-cats a')
    date_element = await item.query_selector('.entry-meta-date')

    if title_element and link_element and img_element and hashtag_elements and date_element:
      title = await title_element.inner_text()
      link = await link_element.get_attribute('href')
      img = await img_element.get_attribute('src')
      hashtags = ', '.join([await tag.inner_text() for tag in hashtag_elements])
      formatted_hashtags = f'#News {format_tags(hashtags)}'
      date = await date_element.inner_text()
      date = date.strip(' |')
      date = format_date(date)

      news_list.append({
        'title': title,
        'link': link,
        'img': img,
        'date': date,
        'hashtag': formatted_hashtags
      })
    else:
      print("Не все элементы найдены для одной новости.")
      print(f"Title Element: {title_element}, Link Element: {link_element}, Img Element: {img_element}, Hashtag Elements: {hashtag_elements}, Date Element: {date_element}")
  return news_list

async def process_trekcore(page):
  await scroll_to_bottom(page)
  news_items = await page.query_selector_all('#tdi_44 .td-cpt-post')
  news_list = []

  for item in news_items:
    title_element = await item.query_selector('.td-module-meta-info h3 a')
    link_element = title_element
    image_element = await item.query_selector('.td-module-thumb span')
    hashtag_element = await item.query_selector('.td-post-category')
    date_element = await item.query_selector('.td-post-date time')

    if title_element and link_element and image_element and hashtag_element and date_element:
      title = await title_element.inner_text()
      link = await link_element.get_attribute('href')
      img = await image_element.get_attribute('data-img-url')
      hashtag = await hashtag_element.inner_html()
      formatted_hashtags = f'#News {format_tags(hashtag)}'
      date = format_date(await date_element.get_attribute('datetime'))

      news_list.append({
        'title': title,
        'link': link,
        'img': img,
        'date': date,
        'hashtag': formatted_hashtags
      })
    else:
      print("Не все элементы найдены для одной новости.")
      print(f"Title Element: {title_element}, Link Element: {link_element}, Img Element: {image_element}, Hashtag Elements: {hashtag_element}, Date Element: {date_element}")
  return news_list

async def main():
  await fetch_news()
  await send_news_from_db(first_run=True)
  await asyncio.sleep(60)

  while True:
    await fetch_news()
    await send_news_from_db(first_run=False)
    await asyncio.sleep(60)

if __name__ == '__main__':
  asyncio.run(main())