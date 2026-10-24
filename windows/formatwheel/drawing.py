"""QPainter artwork and layout for the eight-slot wheel and its HUD."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QIcon, QLinearGradient, QPainter,
                          QPainterPath, QPainterPathStroker, QPen, QPixmap, QRadialGradient)

WHITE = QColor("#f4f4f5")
GOLD = QColor("#f5c745")
LOSS = QColor("#e63d38")
GAIN = QColor("#5cb5e6")


def font(size, bold=False, family="Bahnschrift SemiCondensed"):
    result = QFont(family)
    result.setPixelSize(max(8, round(size)))
    result.setWeight(QFont.Weight.Bold if bold else QFont.Weight.DemiBold)
    return result


def text(painter, value, rect, size=16, color=WHITE, bold=False, align=Qt.AlignmentFlag.AlignCenter, wrap=False):
    painter.save()
    painter.setFont(font(size, bold))
    flags = align | (Qt.TextFlag.TextWordWrap if wrap else Qt.TextFlag.TextSingleLine)
    if not wrap:
        value = QFontMetricsF(painter.font()).elidedText(str(value), Qt.TextElideMode.ElideRight, rect.width())
    painter.setPen(QColor(0, 0, 0, 190))
    painter.drawText(rect.translated(1.5, 2), flags, str(value))
    painter.setPen(color)
    painter.drawText(rect, flags, str(value))
    painter.restore()


def sector(center, inner, outer, index):
    angle = 90 - index * 45
    path = QPainterPath()
    outside = QRectF(center.x() - outer, center.y() - outer, 2 * outer, 2 * outer)
    inside = QRectF(center.x() - inner, center.y() - inner, 2 * inner, 2 * inner)
    path.arcMoveTo(outside, angle + 22.5)
    path.arcTo(outside, angle + 22.5, -45)
    a = math.radians(angle - 22.5)
    path.lineTo(center.x() + inner * math.cos(a), center.y() - inner * math.sin(a))
    path.arcTo(inside, angle - 22.5, 45)
    path.closeSubpath()
    return path


def slot_at(point, center, radius, previous=None):
    dx, dy = point.x() - center.x(), point.y() - center.y()
    if math.hypot(dx, dy) < max(28, radius * .18):
        return None
    theta = math.atan2(dx, -dy) % (2 * math.pi)
    index = int((theta + math.pi / 8) / (math.pi / 4)) % 8
    if previous is not None and index != previous:
        diff = abs((theta - previous * math.pi / 4 + math.pi) % (2 * math.pi) - math.pi)
        if diff < math.pi / 8 + .07:
            return previous
    return index


def tray_icon(accent="#3380e6"):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#202126"), 2))
    for i in range(8):
        p.setBrush(QColor(accent) if i == 0 else WHITE)
        p.drawPath(sector(QPointF(32, 32), 15, 29, i))
    p.end()
    return QIcon(pixmap)


WEAPON_MAP = {
    "img.to.png": "rifle", "img.to.jpg": "pistol", "img.to.heic": "microSMG", "img.to.webp": "smg",
    "img.to.pdf": "rpg", "img.to.avif": "sniper", "img.to.gif": "shotgun", "img.to.tiff": "minigun",
    "img.half": "knuckles", "img.cutout": "knife", "img.ocr": "flashlight", "img.mono": "bat",
    "img.rotate": "wrench", "img.backdrop": "sprayCan", "pdf.to.png": "rifle", "pdf.to.jpg": "pistol",
    "pdf.to.long": "sniper", "pdf.to.docx": "shotgun", "pdf.to.txt": "knuckles", "pdf.to.md": "smg",
    "pdf.to.rtf": "microSMG", "pdf.to.html": "rpg", "pdf.split": "knife", "pdf.merge": "stickyBomb",
    "pdf.rotate": "wrench", "pdf.mono": "bat", "pdf.ocr": "flashlight", "vid.to.mp4": "rifle",
    "vid.to.mov": "pistol", "vid.to.hevc": "sniper", "vid.to.webm": "smg", "vid.to.gif": "shotgun",
    "vid.to.mp3": "microSMG", "vid.to.m4a": "molotov", "vid.to.wav": "minigun", "vid.mute": "silencedPistol",
    "vid.720p": "wrench", "vid.cover": "flashlight", "vid.fast": "smg", "vid.slow": "sniper", "vid.strip": "molotov",
    "aud.to.mp3": "pistol", "aud.to.m4a": "microSMG", "aud.to.wav": "minigun", "aud.to.flac": "rifle",
    "aud.to.aiff": "shotgun", "aud.to.opus": "sniper", "aud.to.alac": "smg", "aud.to.m4r": "stickyBomb",
    "aud.mono": "knife", "aud.loud": "bat", "aud.fast": "smg", "doc.to.pdf": "rpg", "doc.to.docx": "rifle",
    "doc.to.txt": "knuckles", "doc.to.md": "smg", "doc.to.html": "molotov", "doc.to.rtf": "microSMG",
    "doc.to.odt": "shotgun", "doc.to.doc": "pistol", "doc.count": "flashlight", "doc.copy": "knife",
    "gen.zip": "jerryCan", "gen.path": "knuckles", "gen.name": "knife", "gen.sha": "wrench",
}


def weapon_name(action):
    return WEAPON_MAP.get(action, "silencedPistol" if action.endswith(".strip") else "grenade" if action.endswith(".compress") else "pistol")


def weapon(painter, action, rect):
    # The numeric silhouettes are transcribed from the upstream MIT-licensed Weapons.swift.
    from .weapon_art import ART
    pieces = ART.get(weapon_name(action), ART["pistol"])
    shapes, details = [], QPainterPath()
    for operation, args in pieces:
        path = QPainterPath()
        if operation == "rect":
            x, y, w, h, *radius = args
            path.addRoundedRect(QRectF(x, y, w, h), radius[0] if radius else 0, radius[0] if radius else 0)
        elif operation in ("circle", "ellipse", "ring"):
            x, y, r, *more = args
            ry = more[0] if operation == "ellipse" else r
            path.addEllipse(QPointF(x, y), r, ry)
            if operation == "ring":
                stroker = QPainterPathStroker()
                stroker.setWidth(more[0])
                path = stroker.createStroke(path)
        elif operation in ("poly", "line", "bar"):
            points = args[0] if operation == "bar" else args
            path.moveTo(QPointF(*points[0]))
            for point in points[1:]:
                path.lineTo(QPointF(*point))
            if operation == "poly":
                path.closeSubpath()
            elif operation == "line":
                details.addPath(path)
                continue
            else:
                stroker = QPainterPathStroker()
                stroker.setWidth(args[1])
                path = stroker.createStroke(path)
        elif operation == "arc":
            x, y, r, start, end, width = args
            path.arcMoveTo(QRectF(x-r, y-r, 2*r, 2*r), -start)
            path.arcTo(QRectF(x-r, y-r, 2*r, 2*r), -start, -(end-start))
            stroker = QPainterPathStroker()
            stroker.setWidth(width)
            path = stroker.createStroke(path)
        elif operation == "ticks":
            x, end, step, y0, y1 = args
            while x <= end:
                details.moveTo(x, y0)
                details.lineTo(x, y1)
                x += step
            continue
        elif operation == "flame":
            path.moveTo(30, 74)
            path.cubicTo(22, 86, 30, 98, 40, 108)
            path.cubicTo(42, 102, 44, 96, 46, 92)
            path.cubicTo(48, 95, 51, 97, 52, 100)
            path.cubicTo(60, 90, 58, 80, 52, 74)
            path.closeSubpath()
        shapes.append(path)
    bounds = details.boundingRect()
    for path in shapes:
        bounds = bounds.united(path.boundingRect())
    if bounds.isEmpty():
        return
    scale = min(rect.width() / bounds.width(), rect.height() / bounds.height())
    painter.save()
    painter.translate(rect.center())
    painter.scale(scale, -scale)
    painter.translate(-bounds.center())
    painter.setPen(QPen(QColor("#121417"), 3 / scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    gradient = QLinearGradient(bounds.topLeft(), bounds.bottomLeft())
    gradient.setColorAt(0, QColor("#b8bec8"))
    gradient.setColorAt(1, WHITE)
    painter.setBrush(gradient)
    for path in shapes:
        painter.drawPath(path)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#34363c"), max(.7, .8 / scale)))
    painter.drawPath(details)
    painter.restore()


def glyph(p, action, rect, accent):
    p.save()
    p.translate(rect.topLeft())
    scale = min(rect.width(), rect.height()) / 64
    p.scale(scale, scale)
    p.setPen(QPen(QColor("#161820"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QColor("#e9edf4"))
    suffix = action.rsplit(".", 1)[-1]
    if ".to." in action:
        p.drawRoundedRect(QRectF(12, 4, 39, 53), 3, 3)
        p.setBrush(QColor(accent))
        if suffix in {"png", "jpg", "heic", "webp", "avif", "gif", "tiff", "long"}:
            p.drawRoundedRect(QRectF(17, 12, 29, 26), 2, 2)
            p.setPen(QPen(QColor("#f5cc41"), 1))
            p.setBrush(QColor("#f5cc41"))
            p.drawEllipse(QPointF(39, 19), 4, 4)
            p.setBrush(QColor("#77bb71"))
            p.drawPolygon([QPointF(18, 36), QPointF(28, 23), QPointF(36, 32), QPointF(41, 28), QPointF(46, 37)])
        elif action.startswith(("aud.", "vid.")) and suffix in {"mp3", "m4a", "wav", "flac", "aiff", "opus", "alac", "m4r"}:
            p.setPen(QPen(QColor(accent), 4))
            p.drawLine(27, 17, 27, 38)
            p.drawLine(27, 17, 41, 14)
            p.drawLine(41, 14, 41, 35)
            p.setBrush(QColor(accent))
            p.drawEllipse(QRectF(20, 34, 9, 7))
            p.drawEllipse(QRectF(34, 31, 9, 7))
        elif action.startswith("vid."):
            p.drawRoundedRect(QRectF(17, 15, 29, 24), 2, 2)
            p.setBrush(WHITE)
            p.drawPolygon([QPointF(28, 20), QPointF(28, 34), QPointF(39, 27)])
        else:
            p.setPen(QPen(QColor(accent), 3))
            for y in (17, 24, 31):
                p.drawLine(20, y, 42, y)
        text(p, suffix.upper() if suffix != "long" else "LONG", QRectF(10, 39, 44, 17), 12, QColor("#20242a"), True)
    else:
        p.setBrush(QColor("#e2e6ec"))
        p.drawRoundedRect(QRectF(10, 8, 44, 45), 8, 8)
        symbols = {"compress": "↓", "half": "½", "cutout": "✂", "ocr": "Aa", "mono": "◐", "rotate": "↻",
                   "strip": "⌖", "backdrop": "▧", "split": "⋮", "merge": "+", "mute": "×♪", "720p": "720",
                   "cover": "▣", "fast": "»", "slow": "«", "loud": "▂▅▇", "count": "123", "copy": "Aa",
                   "zip": "ZIP", "path": "↗", "name": "TAG", "sha": "#"}
        text(p, symbols.get(suffix, "⋯"), QRectF(9, 11, 46, 38), 23, QColor(accent), True)
    p.restore()


def paint_wheel(p, context, page_index, hover, center, radius, settings, glow=None, pop=1):
    if not context or not context.pages:
        return
    p.save()
    s = radius / 245
    accent = QColor(settings.accent)
    inner = radius * .56
    growth = .9 + .1 * (1 - (1-pop) ** 3)
    p.translate(center)
    p.scale(growth, growth)
    p.translate(-center)
    hub = QRadialGradient(center, inner)
    hub.setColorAt(0, QColor(0, 0, 0, 155))
    hub.setColorAt(1, QColor(0, 0, 0, 10))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(hub)
    p.drawEllipse(center, inner, inner)
    page = context.pages[page_index]
    for i in range(8):
        amount = glow[i] if glow else float(i == hover)
        fill = QRadialGradient(center, radius)
        fill.setColorAt(.56, QColor(74, 76, 81, 190))
        fill.setColorAt(1, QColor(110, 112, 117, 192))
        path = sector(center, inner, radius, i)
        p.setBrush(fill)
        p.setPen(QPen(QColor(255, 255, 255, 180), max(1.2, 1.7*s)))
        p.drawPath(path)
        if amount > .001:
            p.save()
            p.setOpacity(amount)
            lit = QRadialGradient(center, radius)
            light = QColor(accent)
            light.setAlpha(245)
            lit.setColorAt(.55, QColor(190, 213, 248, 130))
            lit.setColorAt(1, light)
            p.fillPath(path, lit)
            p.setPen(QPen(accent, 7*s))
            p.drawArc(QRectF(center.x()-radius+3*s, center.y()-radius+3*s, radius*2-6*s, radius*2-6*s), round((90-i*45-22.2)*16), round(44.4*16))
            p.restore()
        option = page.slots[i] if i < len(page.slots) else None
        if option is None:
            continue
        angle = i * math.pi / 4
        mid = (inner + radius)/2
        point = QPointF(center.x()+math.sin(angle)*mid, center.y()-math.cos(angle)*mid)
        p.save()
        p.setOpacity(1 if option.enabled else .58 if option.ammo in {"当前", "Current"} else .36)
        if settings.get("icons") == "weapons":
            width = (128 - 30*abs(math.sin(angle))) * s
            weapon(p, option.id, QRectF(point.x()-width/2, point.y()-37*s, width, 45*s))
            label = getattr(option, "big", None) or option.ammo
            text(p, label, QRectF(point.x()-65*s, point.y()+10*s, 130*s, 28*s), 19*s, bold=True)
        else:
            glyph(p, option.id, QRectF(point.x()-26*s, point.y()-55*s, 52*s, 52*s), accent.name())
            label = getattr(option, "big", None) or option.title
            text(p, label, QRectF(point.x()-65*s, point.y()+1*s, 130*s, 28*s), (22 if len(label)<7 else 17)*s, bold=True)
            if getattr(option, "big", None) or not option.enabled:
                text(p, option.ammo, QRectF(point.x()-65*s, point.y()+27*s, 130*s, 19*s), 12*s)
        p.restore()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 155), 4*s))
    p.drawEllipse(center, radius, radius)
    p.setPen(QPen(QColor(0, 0, 0, 125), 2.4*s))
    p.drawEllipse(center, inner, inner)
    selected = page.slots[hover] if hover is not None and hover < len(page.slots) else None
    kind = getattr(context.kind, "title", str(context.kind))
    if callable(kind):
        kind = kind()
    text(p, f"{kind} · {page.name}", QRectF(center.x()-inner*.85, center.y()-inner*.61, inner*1.7, 25*s), 14*s)
    headline = selected.title if selected else getattr(context, "headline", "格式轮盘 / FormatWheel")
    text(p, headline, QRectF(center.x()-inner*.84, center.y()-inner*.37, inner*1.68, 42*s), (28 if selected else 22)*s, bold=True)
    detail = (selected.detail if selected.enabled else selected.note or "现在用不了 / Unavailable") if selected else getattr(context, "summary", "拖入文件开始 / Drop files to begin")
    text(p, detail, QRectF(center.x()-inner*.72, center.y()+3*s, inner*1.44, inner*.5), 13.5*s, WHITE if selected is None or selected.enabled else LOSS.lighter(140), wrap=True)
    if len(context.pages)>1:
        text(p, f"‹  {page_index+1} / {len(context.pages)}  ›", QRectF(center.x()-inner*.7, center.y()+inner*.47, inner*1.4, 26*s), 18*s)
    p.restore()


def panel(p, rect, accent):
    p.fillRect(rect, QColor(0, 0, 0, 192))
    p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), 3), accent)


def paint_stats(p, context, selected, rect, accent, shown=None):
    labels = getattr(context, "stat_labels", getattr(context, "statLabels", []))
    if not labels:
        return
    panel(p, rect, accent)
    title = selected.title if selected else context.headline
    detail = (f"{context.headline} → {selected.title}" if selected.enabled else selected.note) if selected else context.summary
    text(p, title, QRectF(rect.x()+16, rect.y()+10, rect.width()-32, 27), 20, bold=True, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    text(p, detail or "", QRectF(rect.x()+16, rect.y()+38, rect.width()-32, 23), 12, QColor("#bbbbbf"), align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    base = context.base
    values = shown or (getattr(selected, "stats", None) if selected and selected.enabled else None) or base
    for i, label in enumerate(labels):
        y = rect.y()+72+i*27
        text(p, label, QRectF(rect.x()+16, y-4, 84, 23), 14, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bar = QRectF(rect.x()+104, y+4, rect.width()-120, 8)
        p.fillRect(bar, QColor(255, 255, 255, 42))
        start = base[i] if i<len(base) else 0
        value = values[i] if i<len(values) else start
        low, high = min(start, value), max(start, value)
        p.fillRect(QRectF(bar.x(), bar.y(), bar.width()*low, 8), WHITE)
        p.fillRect(QRectF(bar.x()+bar.width()*low, bar.y(), bar.width()*(high-low), 8), GAIN if value>start else LOSS)
        for tick in range(1, 5):
            p.fillRect(QRectF(bar.x()+bar.width()*tick/5-1, bar.y(), 2, 8), QColor(0, 0, 0, 190))


def paint_wanted(p, rect, level, reasons, phase, evading=False, caption=None):
    if not level:
        return
    p.save()
    flash = QColor(215, 38, 38, 70) if int(phase*5)%2 else QColor(35, 100, 255, 70)
    gradient = QRadialGradient(rect.center(), rect.width()/2)
    gradient.setColorAt(0, flash)
    gradient.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(rect, gradient)
    for i in range(5):
        color = WHITE if i < level and (not evading or int(phase*3)%2 == 0) else QColor("#666971")
        x = rect.x()+rect.width()-40*(5-i)
        text(p, "★", QRectF(x, rect.y(), 40, 42), 35, color, True)
    caption = caption or ("松手 = 甩掉警察 / Release to erase traces" if evading else " · ".join(reasons))
    text(p, caption, QRectF(rect.x(), rect.y()+44, rect.width(), 24), 12)
    p.restore()
