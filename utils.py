import asyncio
import base64
import re
import requests

def extract_and_format_date(url):
    match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
    if match:
        year, month, day = match.groups()
        return f"{day}.{month}.{year}"
    return None

def is_valid_image(img_str):
    if is_base64_image(img_str):
        return True
    return is_valid_image_url(img_str)

def is_valid_image_url(url):
    try:
        response = requests.get(url, stream=True)
        if response.status_code == 200 and 'image' in response.headers['Content-Type']:
            return True
    except Exception as e:
        print(f"Ошибка при проверке URL изображения: {e}")
    return False

def is_base64_image(img_str):
    if img_str.startswith('data:image'):
        try:
            header, data = img_str.split(',', 1)
            base64.b64decode(data)
            return True
        except Exception as e:
            print(f"Ошибка при проверке base64 изображения: {e}")
            return False
    return False

async def scroll_to_bottom(page, step=1000, wait_time=1):
    """Функция для скролла страницы вниз"""
    current_height = 0
    while True:
        # Прокручиваем страницу вниз
        await page.evaluate(f"window.scrollBy(0, {step})")
        await asyncio.sleep(wait_time)  # Ждем немного, чтобы контент подгрузился
        
        # Проверяем текущую высоту страницы
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == current_height:  # Если высота больше не меняется, значит достигли низа страницы
            break
        current_height = new_height