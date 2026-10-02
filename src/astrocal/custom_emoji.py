"""HTML-экспорт с custom emoji Стаса; обычный TXT сохраняет Unicode."""
from html import escape

# Идентификаторы из сообщения Стаса 25.09.2026; не credentials.
PLANETS = {
    "⚫": ("🫧", "5192845129945202024"),
    "⚪": ("🔥", "5341774314934911701"),
    "🔴": ("🪐", "5224485896316805285"),
    "🟠": ("🪐", "5393132627622397701"),
    "🔵": ("❄️", "5201812282924873515"),
    "🔷": ("🌊", "5199809599804291117"),
}


def telegram_html(text):
    lines = []
    for line in text.splitlines():
        pair = next(((icon, value) for icon, value in PLANETS.items() if line.startswith(icon)), None)
        if pair:
            icon, (fallback, identifier) = pair
            lines.append(f'<tg-emoji emoji-id="{identifier}">{fallback}</tg-emoji>' + escape(line[len(icon):]))
        else:
            lines.append(escape(line))
    return "\n".join(lines)
