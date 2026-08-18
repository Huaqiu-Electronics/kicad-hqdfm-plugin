import os

from kicad_dfm.child_frame.diagram_catalog import DIAGRAM_BY_ITEM, DIAGRAM_LABELS_EN
from kicad_dfm.child_frame.picture_match_path import normalize, picture_bitmap_for
from kicad_dfm.picture import GetImagePath


DIAGRAM_NAMES = {
    normalize(alias): picture_name
    for picture_name, config in DIAGRAM_BY_ITEM.items()
    for alias in config["aliases"]
}


def diagram_name_for(value):
    return DIAGRAM_NAMES.get(normalize(value))


def diagram_path_for(value):
    picture_name = diagram_name_for(value)
    if not picture_name:
        return None
    config = DIAGRAM_BY_ITEM[picture_name]
    return GetImagePath(os.path.join("diagram", config["image"]))


def diagram_bitmap_for(value, language_string="", max_size=None, fallback=True):

    picture_name = diagram_name_for(value)
    if not picture_name:
        return _fallback_bitmap(value, language_string, fallback)

    config = DIAGRAM_BY_ITEM[picture_name]
    path = diagram_path_for(value)
    if not os.path.exists(path):
        return _fallback_bitmap(value, language_string, fallback)

    import wx

    bitmap = wx.Bitmap(path)
    if not bitmap.IsOk():
        return _fallback_bitmap(value, language_string, fallback)

    image = bitmap.ConvertToImage()
    if max_size:
        image = scale_image_to_fit(image, max_size[0], max_size[1])
    width = image.GetWidth()
    height = image.GetHeight()
    rendered = wx.Bitmap(width, height)
    memory = wx.MemoryDC(rendered)
    memory.SetBackground(wx.Brush(wx.WHITE))
    memory.Clear()
    memory.DrawBitmap(wx.Bitmap(image), 0, 0, True)

    try:
        _draw_labels(memory, config, width, height)
    finally:
        memory.SelectObject(wx.NullBitmap)

    return rendered


def _fallback_bitmap(value, language_string, fallback):
    if not fallback:
        return None
    return picture_bitmap_for(value, language_string)


def scaled_bitmap(bitmap, max_width, max_height):
    if not bitmap.IsOk():
        return bitmap
    width = bitmap.GetWidth()
    height = bitmap.GetHeight()
    if width <= max_width and height <= max_height:
        return bitmap
    scale = min(float(max_width) / width, float(max_height) / height)
    image = bitmap.ConvertToImage()
    return wx_bitmap_from_image(image, max(1, int(width * scale)), max(1, int(height * scale)))


def scale_image_to_fit(image, max_width, max_height):
    width = image.GetWidth()
    height = image.GetHeight()
    if width <= max_width and height <= max_height:
        return image
    scale = min(float(max_width) / width, float(max_height) / height)
    return image.Scale(max(1, int(width * scale)), max(1, int(height * scale)))


def wx_bitmap_from_image(image, width, height):
    import wx

    return wx.Bitmap(image.Scale(width, height))


def _draw_labels(dc, config, width, height):
    import wx

    dc.SetBackgroundMode(wx.TRANSPARENT)
    dc.SetPen(wx.Pen(wx.Colour(37, 99, 235), 2))
    dc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
    dc.SetTextForeground(wx.Colour(16, 24, 40))
    dc.SetTextBackground(wx.Colour(255, 255, 255))
    font = dc.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    font.SetPointSize(10)
    dc.SetFont(font)
    for label in config.get("labels", ()):
        anchor_x, anchor_y = _point(label["anchor"], width, height)
        label_x, label_y = _point(label["label"], width, height)
        dc.DrawLine(label_x, label_y, anchor_x, anchor_y)
        text = label_text(label)
        lines = wrap_text(dc, text, label_width(width))
        text_w = max(dc.GetTextExtent(line)[0] for line in lines)
        text_h = sum(dc.GetTextExtent(line)[1] for line in lines) + max(0, len(lines) - 1) * 2
        text_x = _aligned_x(label_x, text_w, label.get("align", "center"))
        text_x = max(8, min(text_x, width - text_w - 8))
        text_y = max(8, label_y - text_h)
        padding = 4
        dc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        dc.DrawRoundedRectangle(
            text_x - padding,
            text_y - padding,
            text_w + padding * 2,
            text_h + padding * 2,
            4,
        )
        current_y = text_y
        for line in lines:
            dc.DrawText(line, text_x, current_y)
            current_y += dc.GetTextExtent(line)[1] + 2


def _draw_legend(dc, config, image_height):
    import wx

    legend = legend_entries(config)
    if not legend:
        return
    dc.SetTextForeground(wx.Colour(52, 64, 84))
    font = dc.GetFont()
    font.SetWeight(wx.FONTWEIGHT_NORMAL)
    font.SetPointSize(9)
    dc.SetFont(font)
    y = image_height + 4
    for symbol, key in legend:
        dc.DrawText("{0} = {1}".format(symbol, translate(key)), 10, y)
        y += 20


def legend_entries(config):
    labels = list(config.get("labels", ()))
    symbols_by_key = {
        label["key"]: label["symbol"]
        for label in labels
        if label.get("key") and label.get("symbol")
    }
    entries = []
    for index, key in enumerate(config.get("legend", ())):
        entries.append((symbols_by_key.get(key, str(index + 1)), key))
    return entries


def label_text(label, translator=None):
    return translate(label["key"], translator)


def wrap_text(dc, text, max_width):
    if dc.GetTextExtent(text)[0] <= max_width:
        return [text]
    words = text.split()
    if len(words) <= 1:
        return wrap_unspaced_text(dc, text, max_width)
    lines = []
    current = ""
    for word in words:
        candidate = current + " " + word
        if dc.GetTextExtent(candidate)[0] <= max_width:
            current = candidate
        elif not current:
            lines.extend(wrap_unspaced_text(dc, word, max_width))
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrap_unspaced_text(dc, text, max_width):
    lines = []
    current = ""
    for char in text:
        candidate = current + char
        if not current or dc.GetTextExtent(candidate)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines or [text]


def label_width(image_width):
    return max(48, min(180, image_width - 24, int(image_width * 0.36)))


def _point(value, width, height):
    return int(value[0] * width), int(value[1] * height)


def _aligned_x(x, text_width, align):
    if align == "left":
        return x
    if align == "right":
        return x - text_width
    return x - text_width // 2


def translate(key, translator=None):
    try:
        text = (translator or _)(key)
    except NameError:
        text = key
    if text == key:
        return DIAGRAM_LABELS_EN.get(key, key)
    return text
