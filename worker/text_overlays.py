"""Validated timed text cards shared by editor persistence and FFmpeg export."""
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont


def validate_text_overlays(raw, duration):
    if not isinstance(raw, list) or len(raw) > 12:
        raise ValueError('Use up to 12 text overlays')
    clean = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('Invalid text overlay')
        identifier = item.get('id')
        text = item.get('text')
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', identifier) or identifier in seen:
            raise ValueError('Each text overlay needs a unique ID')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 80 or '\n' in text:
            raise ValueError('Text overlays need 1–80 characters on one line')
        try:
            start, end = float(item['start']), float(item['end'])
            x, y = float(item['x']), float(item['y'])
            size = int(item['size'])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError('Invalid text overlay timing or position') from None
        if not all(map(math.isfinite, (start, end, x, y))) or not (0 <= start < end <= duration and .08 <= x <= .92 and .08 <= y <= .92 and 24 <= size <= 100):
            raise ValueError('Keep text overlays inside the video and source window')
        color, background = item.get('color'), item.get('background')
        if not all(isinstance(c, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in (color, background)):
            raise ValueError('Use six-digit text colors')
        clean.append({'id': identifier, 'text': text.strip(), 'start': round(start, 3), 'end': round(end, 3),
                      'x': round(x, 4), 'y': round(y, 4), 'size': size, 'color': color, 'background': background})
        seen.add(identifier)
    return sorted(clean, key=lambda item: (item['start'], item['id']))


def draw_text_overlay(item, width, height, output):
    """Render a transparent full-frame card; user text never enters an FFmpeg expression."""
    image = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(image)
    devanagari=bool(re.search('[\u0900-\u097f]',item['text']))
    multilingual=any(ord(character)>127 for character in item['text'])
    candidates=[]
    if devanagari:
        candidates += [Path('/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc'),
                       Path('/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf')]
    elif multilingual:
        candidates += [Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),
                       Path('/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf')]
    candidates += [Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
                   Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
    font_path = next((path for path in candidates if path.exists()), None)
    if not font_path:
        raise RuntimeError('A bold text font is missing')
    font = ImageFont.truetype(str(font_path), max(12, round(item['size'] * width / 1080)))
    while draw.textlength(item['text'], font=font) > width * .84 and font.size > 12:
        font = font.font_variant(size=font.size - 2)
    center = (round(item['x'] * width), round(item['y'] * height))
    box = draw.textbbox(center, item['text'], font=font, anchor='mm', stroke_width=1)
    pad = max(7, round(font.size * .24))
    draw.rounded_rectangle((box[0]-pad, box[1]-pad, box[2]+pad, box[3]+pad),
                           radius=max(4, round(font.size * .2)), fill=item['background'])
    draw.text(center, item['text'], font=font, anchor='mm', fill=item['color'], stroke_width=1, stroke_fill='#000000')
    image.save(output)
