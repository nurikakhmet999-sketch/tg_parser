import re

def clean_text(text: str, blacklist: list, signature: str = None) -> str:
    if not text:
        return ""

    # убираем ссылки
    text = re.sub(r'http\S+|t\.me/\S+', '', text)
    # убираем упоминания
    text = re.sub(r'@\w+', '', text)

    # убираем фразы из чёрного списка
    for phrase in blacklist:
        text = re.sub(re.escape(phrase), '', text, flags=re.IGNORECASE)

    text = re.sub(r'\s+', ' ', text).strip()

    if signature:
        text += f"\n\n{signature}"

    return text
