from pathlib import Path
import math

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kicad_dfm" / "picture" / "diagram"

W, H = 520, 220
OUTPUT_W, OUTPUT_H = 300, 170
SCALE = 3

BG = "#075f49"
BOARD = "#0a6b53"
COPPER = "#e2c92b"
COPPER_DARK = "#9c9500"
TRACE = "#2dae84"
TRACE_DARK = "#14765f"
MASK = "#29a87d"
HOLE = "#08130e"
EDGE = "#d6f5eb"
DIM = "#f5fffb"
WARN = "#e02020"
SUB = "#6f7a78"
LAYER = "#9a9f9e"


def sc(v):
    return int(round(v * SCALE))


def pts(values):
    return [(sc(x), sc(y)) for x, y in values]


def canvas():
    img = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    draw = ImageDraw.Draw(img)
    return img, draw


def save(name, img):
    img = img.resize((OUTPUT_W, OUTPUT_H), Image.Resampling.LANCZOS)
    img.save(OUT / f"{name}.png", optimize=True)


def line(draw, values, fill=TRACE, width=10, joint="curve"):
    draw.line(pts(values), fill=fill, width=sc(width), joint=joint)


def rect(draw, xy, fill, outline=None, width=2):
    draw.rectangle(tuple(sc(v) for v in xy), fill=fill, outline=outline, width=sc(width))


def round_rect(draw, xy, radius=8, fill=None, outline=None, width=2):
    draw.rounded_rectangle(tuple(sc(v) for v in xy), radius=sc(radius), fill=fill, outline=outline, width=sc(width))


def ellipse(draw, xy, fill=None, outline=None, width=2):
    draw.ellipse(tuple(sc(v) for v in xy), fill=fill, outline=outline, width=sc(width))


def poly(draw, values, fill, outline=None):
    draw.polygon(pts(values), fill=fill, outline=outline)


def via(draw, cx, cy, r=18, ring=COPPER):
    ellipse(draw, (cx - r, cy - r, cx + r, cy + r), fill=ring)
    ellipse(draw, (cx - r * 0.45, cy - r * 0.45, cx + r * 0.45, cy + r * 0.45), fill=HOLE)


def pad(draw, xy, hole=False, fill=COPPER):
    round_rect(draw, xy, 6, fill=fill)
    if hole:
        cx = (xy[0] + xy[2]) / 2
        cy = (xy[1] + xy[3]) / 2
        ellipse(draw, (cx - 10, cy - 10, cx + 10, cy + 10), fill=HOLE)


def slot(draw, xy, fill=COPPER, hole_fill=HOLE):
    round_rect(draw, xy, (xy[3] - xy[1]) / 2, fill=fill)
    inset = 9
    round_rect(draw, (xy[0] + inset, xy[1] + inset, xy[2] - inset, xy[3] - inset), (xy[3] - xy[1]) / 2, fill=hole_fill)


def warn_circle(draw, xy, width=4):
    ellipse(draw, xy, outline=WARN, width=width)


def warn_cross(draw, cx, cy, size=20):
    line(draw, ((cx - size, cy - size), (cx + size, cy + size)), WARN, 6)
    line(draw, ((cx + size, cy - size), (cx - size, cy + size)), WARN, 6)


def check_mark(draw, cx, cy, size=22):
    line(draw, ((cx - size, cy), (cx - size / 3, cy + size / 2), (cx + size, cy - size)), WARN, 7)


def arrow(draw, start, end, fill=DIM, width=3):
    line(draw, (start, end), fill, width)
    sx, sy = start
    ex, ey = end
    ang = math.atan2(ey - sy, ex - sx)
    head = 10
    spread = 0.55
    p1 = (ex - math.cos(ang - spread) * head, ey - math.sin(ang - spread) * head)
    p2 = (ex - math.cos(ang + spread) * head, ey - math.sin(ang + spread) * head)
    poly(draw, (end, p1, p2), fill)


def dim_h(draw, x1, x2, y, fill=DIM):
    arrow(draw, (x1, y), (x2, y), fill, 2)
    arrow(draw, (x2, y), (x1, y), fill, 2)
    line(draw, ((x1, y - 16), (x1, y + 16)), fill, 2)
    line(draw, ((x2, y - 16), (x2, y + 16)), fill, 2)


def dim_v(draw, x, y1, y2, fill=DIM):
    arrow(draw, (x, y1), (x, y2), fill, 2)
    arrow(draw, (x, y2), (x, y1), fill, 2)
    line(draw, ((x - 16, y1), (x + 16, y1)), fill, 2)
    line(draw, ((x - 16, y2), (x + 16, y2)), fill, 2)


def board(draw, xy):
    round_rect(draw, xy, 4, fill=BOARD, outline=TRACE_DARK, width=2)


def acute_angle(draw):
    line(draw, ((40, 74), (88, 74), (88, 128)), TRACE, 9)
    line(draw, ((130, 74), (212, 74), (130, 130)), TRACE, 9)
    line(draw, ((265, 130), (340, 130), (340, 74)), TRACE, 9)
    line(draw, ((358, 132), (432, 132), (495, 76)), TRACE, 9)
    warn_circle(draw, (113, 57, 226, 144), 4)


def bga(draw):
    for x in range(60, 205, 34):
        for y in range(62, 166, 34):
            via(draw, x, y, 10)
    line(draw, ((250, 65), (250, 150)), TRACE, 6)
    line(draw, ((285, 65), (285, 150)), TRACE, 6)
    pad(draw, (325, 86, 350, 132))
    for y in (70, 92, 114, 136):
        line(draw, ((390, y), (480, y)), COPPER, 8)
    dim_h(draw, 250, 285, 162)
    dim_h(draw, 390, 480, 156)
    warn_circle(draw, (318, 78, 358, 140), 3)


def blind2blind(draw):
    ys = [62, 85, 108, 131, 154]
    for y in ys:
        line(draw, ((145, y), (390, y)), COPPER, 5)
    rect(draw, (205, 65, 210, 155), COPPER)
    rect(draw, (255, 85, 260, 130), COPPER)
    rect(draw, (345, 105, 350, 157), COPPER)
    warn_circle(draw, (330, 115, 360, 145), 4)


def breakage_line(draw):
    for y in (85, 112, 139):
        line(draw, ((25, y), (125, y)), COPPER, 14)
    line(draw, ((100, 139), (145, 139), (180, 112), (235, 112), (270, 150), (345, 150), (390, 118), (520, 118)), TRACE, 10)
    line(draw, ((102, 85), (195, 85), (245, 85), (320, 85), (370, 112)), TRACE, 10)
    for x, y in ((145, 139), (370, 112), (390, 85)):
        via(draw, x, y, 14, TRACE)
    pad(draw, (208, 74, 290, 104), hole=False)
    pad(draw, (208, 124, 290, 154), hole=False)
    warn_circle(draw, (82, 124, 134, 176), 4)
    warn_circle(draw, (345, 92, 395, 142), 4)
    warn_circle(draw, (390, 125, 455, 185), 4)


def dangling_tracks(draw):
    line(draw, ((35, 115), (205, 115)), TRACE, 12)
    pad(draw, (55, 82, 120, 148))
    warn_circle(draw, (180, 90, 230, 140), 4)
    line(draw, ((315, 115), (485, 115)), TRACE, 12)
    via(draw, 465, 115, 24, TRACE)
    warn_circle(draw, (290, 90, 340, 140), 4)


def copper2edge(draw):
    board(draw, (250, 60, 470, 170))
    for x in (295, 323, 351, 379):
        line(draw, ((x, 70), (x, 132)), COPPER, 16)
    line(draw, ((260, 152), (430, 152), (430, 120), (460, 120)), TRACE, 8)
    via(draw, 305, 150, 10, TRACE)
    via(draw, 432, 120, 10, TRACE)
    dim_h(draw, 250, 295, 50)
    dim_v(draw, 480, 60, 170)
    warn_circle(draw, (236, 48, 318, 90), 3)


def pth2edge(draw):
    """PTH/half-hole clearance to the routed board outline."""
    line(draw, ((40, 155), (480, 155)), EDGE, 4)
    via(draw, 165, 123, 36, COPPER)
    ellipse(draw, (149, 107, 181, 139), fill=COPPER_DARK)
    via(draw, 345, 95, 36, COPPER)
    ellipse(draw, (329, 79, 361, 111), fill=COPPER_DARK)
    line(draw, ((370, 70), (430, 10)), TRACE, 12)
    dim_v(draw, 92, 123, 155)


def via2edge(draw):
    """Via drill clearance to the routed board outline."""
    board(draw, (40, 40, 480, 165))
    line(draw, ((42, 165), (478, 165)), EDGE, 4)
    for x, y in ((90, 105), (125, 135), (175, 122), (230, 142), (285, 110), (350, 135), (410, 105)):
        via(draw, x, y, 10, TRACE)
    pad(draw, (185, 55, 225, 95))
    pad(draw, (238, 55, 278, 95))
    pad(draw, (291, 55, 331, 95))
    dim_v(draw, 285, 120, 165)


def npth2edge(draw):
    """Non-plated/mounting-hole clearance to the routed board outline."""
    line(draw, ((40, 155), (480, 155)), EDGE, 4)
    ellipse(draw, (125, 75, 205, 155), fill=SUB, outline=EDGE, width=2)
    ellipse(draw, (315, 65, 395, 145), fill=SUB, outline=EDGE, width=2)
    dim_v(draw, 92, 115, 155)


def grid_spacing(draw):
    round_rect(draw, (200, 55, 360, 175), 8, fill=MASK)
    for x in range(220, 342, 30):
        for y in range(75, 158, 25):
            rect(draw, (x, y, x + 12, y + 10), BG)
    dim_h(draw, 220, 250, 190)
    dim_v(draw, 380, 75, 100)


def grid_width(draw):
    round_rect(draw, (200, 55, 360, 175), 8, fill=MASK)
    for x in range(220, 342, 30):
        for y in range(75, 158, 25):
            rect(draw, (x, y, x + 12, y + 10), BG)
    dim_h(draw, 220, 232, 190)
    arrow(draw, (392, 86), (352, 86))


def hole_density(draw):
    rect(draw, (45, 120, 475, 172), COPPER)
    dots = [
        (65, 137, 4), (78, 158, 5), (94, 143, 3), (112, 154, 4), (128, 134, 3),
        (146, 158, 4), (170, 143, 2), (200, 154, 3), (230, 136, 9), (260, 158, 3),
        (288, 140, 3), (306, 148, 3), (335, 136, 9), (365, 158, 2), (392, 145, 3),
        (430, 160, 6), (455, 135, 3), (472, 158, 4)
    ]
    for cx, cy, r in dots:
        ellipse(draw, (cx - r, cy - r, cx + r, cy + r), fill=HOLE)
    warn_circle(draw, (219, 125, 241, 147), 3)
    warn_circle(draw, (326, 127, 344, 145), 3)


def hole_half(draw):
    board(draw, (40, 65, 480, 160))
    for x in range(85, 455, 34):
        via(draw, x, 111, 16)
        rect(draw, (x - 16, 95, x, 127), BG)
    line(draw, ((42, 160), (478, 160)), EDGE, 4)
    dim_h(draw, 85, 119, 54)
    dim_h(draw, 119, 153, 182)
    warn_circle(draw, (70, 78, 126, 136), 3)


def hole_spuared(draw):
    pad(draw, (70, 75, 122, 127), hole=False)
    rect(draw, (84, 88, 108, 114), HOLE)
    pad(draw, (205, 75, 257, 127), hole=False)
    ellipse(draw, (219, 89, 243, 113), fill=HOLE)
    arrow(draw, (135, 101), (190, 101))
    for x in (50, 83, 116, 149):
        pad(draw, (x, 155, x + 26, 185), hole=True)
    warn_cross(draw, 95, 196, 13)
    for x in (320, 353, 386, 419):
        pad(draw, (x, 155, x + 26, 185), hole=True)
    check_mark(draw, 375, 190, 16)


def invalid_via(draw):
    line(draw, ((0, 130), (80, 48), (170, 48), (205, 88)), TRACE, 12)
    line(draw, ((0, 170), (80, 88), (165, 88), (198, 126)), TRACE, 8)
    line(draw, ((70, 190), (150, 130), (285, 130)), TRACE, 10)
    via(draw, 105, 116, 20, TRACE)
    warn_circle(draw, (78, 88, 132, 142), 4)
    for x in (330, 395, 455):
        rect(draw, (x, 70, x + 18, 158), COPPER)
    for y in (78, 108, 138):
        line(draw, ((305, y), (500, y)), COPPER, 5)
    warn_circle(draw, (382, 70, 412, 160), 4)


def isolated_copper(draw):
    rect(draw, (75, 75, 470, 158), COPPER)
    line(draw, ((135, 75), (170, 110), (170, 158)), BG, 5)
    line(draw, ((305, 75), (255, 125), (210, 125)), BG, 5)
    line(draw, ((390, 75), (335, 158)), BG, 5)
    for x, y in ((95, 92), (150, 138), (215, 95), (250, 140), (420, 98), (420, 138)):
        ellipse(draw, (x - 5, y - 5, x + 5, y + 5), fill=HOLE)
    warn_circle(draw, (72, 70, 178, 164), 3)


def line_width(draw):
    via(draw, 55, 110, 26)
    line(draw, ((80, 110), (170, 110)), TRACE, 12)
    line(draw, ((170, 110), (270, 110)), TRACE, 26)
    line(draw, ((270, 110), (458, 110)), TRACE, 46)
    pad(draw, (455, 82, 505, 138), hole=True)
    dim_v(draw, 115, 94, 126)
    dim_v(draw, 236, 82, 138)
    dim_v(draw, 386, 58, 162)


def line2line(draw):
    line(draw, ((70, 92), (150, 92), (160, 82), (305, 82), (318, 72), (470, 72)), TRACE, 10)
    line(draw, ((70, 120), (150, 120), (160, 132), (305, 132), (318, 145), (470, 145)), TRACE, 10)
    dim_v(draw, 105, 92, 120)
    dim_v(draw, 238, 82, 132)
    dim_v(draw, 398, 72, 145)


def line2pth_common(draw):
    pad(draw, (130, 87, 180, 137), hole=True)
    line(draw, ((185, 112), (280, 112), (320, 82), (470, 82)), TRACE, 8)
    line(draw, ((185, 150), (300, 150), (350, 128), (470, 128)), TRACE, 8)
    dim_v(draw, 500, 82, 128)
    dim_h(draw, 180, 320, 62)
    warn_circle(draw, (118, 75, 193, 150), 4)


def max_diameter(draw):
    via(draw, 150, 115, 38)
    via(draw, 385, 115, 50, TRACE)
    dim_h(draw, 112, 188, 168)
    dim_h(draw, 335, 435, 168)
    warn_circle(draw, (330, 60, 440, 170), 4)


def max_diameter_blind_buried(draw):
    for y in (72, 100, 128, 156):
        line(draw, ((150, y), (380, y)), COPPER, 4)
    rect(draw, (150, 78, 380, 150), LAYER, outline=COPPER, width=2)
    rect(draw, (220, 95, 225, 150), COPPER)
    rect(draw, (275, 72, 280, 128), COPPER)
    rect(draw, (335, 72, 340, 155), COPPER)
    warn_circle(draw, (322, 62, 352, 165), 4)


def max_slot(draw):
    slot(draw, (70, 85, 190, 145))
    slot(draw, (350, 85, 470, 145), fill=TRACE)
    dim_v(draw, 205, 85, 145)
    warn_circle(draw, (55, 70, 205, 160), 4)


def max_slot_length(draw):
    slot(draw, (105, 85, 415, 145), fill="#ffb34d", hole_fill=SUB)
    dim_h(draw, 105, 415, 168)
    dim_v(draw, 260, 85, 145)


def min_diameter(draw):
    via(draw, 150, 118, 36)
    via(draw, 360, 118, 18)
    dim_h(draw, 114, 186, 170)
    dim_h(draw, 342, 378, 170)
    warn_circle(draw, (335, 92, 385, 144), 4)


def min_slot(draw):
    slot(draw, (80, 100, 210, 148))
    slot(draw, (305, 84, 455, 154))
    for cx in (340, 375, 410):
        ellipse(draw, (cx - 22, 94, cx + 22, 144), fill=HOLE, outline=SUB, width=sc(2))
    arrow(draw, (212, 124), (306, 124))
    warn_circle(draw, (318, 92, 430, 146), 4)


def min_thick_diameter(draw):
    rect(draw, (65, 135, 195, 170), LAYER)
    rect(draw, (245, 135, 405, 170), LAYER)
    line(draw, ((220, 70), (220, 168)), DIM, 12)
    line(draw, ((220, 70), (230, 92), (214, 116), (228, 140), (220, 168)), SUB, 4)
    dim_h(draw, 207, 233, 112)
    dim_v(draw, 420, 135, 170)
    warn_circle(draw, (199, 62, 239, 176), 4)


def pth_np_insmd(draw, npth=False):
    line(draw, ((45, 135), (220, 135)), TRACE, 12)
    pad(draw, (75, 86, 128, 145), hole=True)
    pad(draw, (142, 96, 198, 147), hole=False)
    line(draw, ((290, 135), (500, 135)), TRACE, 12)
    pad(draw, (355, 92, 465, 150), hole=False)
    if npth:
        ellipse(draw, (382, 48, 462, 128), fill=HOLE)
        warn_cross(draw, 488, 156, 18)
    else:
        via(draw, 320, 124, 22, TRACE)
        warn_cross(draw, 488, 156, 18)
    warn_circle(draw, (365, 78, 475, 156), 4)


def npth2copper(draw):
    rect(draw, (60, 55, 185, 112), MASK)
    line(draw, ((110, 55), (165, 155), (230, 155), (360, 55)), TRACE, 8)
    line(draw, ((115, 182), (260, 68), (360, 68)), TRACE, 8)
    pad(draw, (95, 120, 135, 160))
    pad(draw, (155, 120, 195, 160))
    ellipse(draw, (215, 82, 290, 157), fill=HOLE)
    for p in ((205, 95), (202, 128), (292, 112), (283, 145)):
        arrow(draw, p, (250, 120), WARN, 3)


def pad_spacing_base(draw):
    pad(draw, (120, 72, 190, 115))
    pad(draw, (120, 132, 190, 175))
    dim_v(draw, 205, 115, 132)
    for x in (290, 322, 354, 386):
        pad(draw, (x, 72, x + 28, 175))
    dim_h(draw, 318, 354, 190)


def pad2line(draw):
    line(draw, ((45, 140), (245, 140), (360, 140), (470, 55)), TRACE, 8)
    pad(draw, (245, 90, 365, 124))
    dim_v(draw, 225, 124, 140)
    warn_circle(draw, (220, 82, 375, 150), 4)


def pad2pad(draw):
    line(draw, ((40, 140), (170, 140)), TRACE, 12)
    via(draw, 90, 140, 22, TRACE)
    via(draw, 135, 140, 22, TRACE)
    dim_h(draw, 90, 135, 100)
    line(draw, ((315, 88), (485, 42)), TRACE, 8)
    line(draw, ((315, 142), (485, 88)), TRACE, 8)
    pad(draw, (285, 82, 405, 108))
    pad(draw, (285, 132, 405, 158))
    dim_v(draw, 265, 108, 132)
    warn_circle(draw, (62, 110, 158, 170), 4)


def pth_difference_net(draw):
    for x in (85, 145, 205, 265):
        pad(draw, (x - 25, 105, x + 25, 155), hole=True)
    line(draw, ((60, 105), (290, 105), (290, 155), (60, 155), (60, 105)), EDGE, 3)
    dim_h(draw, 270, 350, 92)
    for y in (60, 84, 108, 132, 156):
        pad(draw, (405, y, 465, y + 18), hole=True)
        line(draw, ((465, y + 9), (510, y + 9)), TRACE, 6)


def slot_length_width(draw):
    slot(draw, (80, 75, 205, 130))
    slot(draw, (330, 75, 455, 145))
    dim_h(draw, 80, 205, 158)
    dim_v(draw, 222, 75, 130)
    dim_h(draw, 330, 455, 170)
    warn_circle(draw, (318, 65, 462, 152), 4)


def smd2edge(draw):
    line(draw, ((35, 165), (500, 165)), EDGE, 4)
    pad(draw, (180, 105, 245, 148))
    pad(draw, (272, 105, 337, 148))
    for x in (385, 430, 475):
        pad(draw, (x, 50, x + 25, 155))
    dim_v(draw, 155, 148, 165)
    warn_circle(draw, (170, 95, 346, 174), 4)


def soldmask_lack(draw):
    for x in (205, 255, 305):
        line(draw, ((x, 75), (x, 165)), MASK, 14)
    for x in (230, 280):
        line(draw, ((x, 70), (x, 140)), COPPER, 14)
    line(draw, ((195, 155), (340, 155)), EDGE, 4)
    for x in (205, 255, 305):
        ellipse(draw, (x - 8, 147, x + 8, 163), fill=BG, outline=EDGE, width=sc(3))
    warn_circle(draw, (188, 136, 324, 176), 4)


def solder_mask_bridge(draw):
    for x in (145, 325):
        round_rect(draw, (x, 72, x + 95, 155), 10, fill=MASK)
        pad(draw, (x + 14, 88, x + 81, 139))
    dim_h(draw, 240, 325, 175)
    warn_circle(draw, (225, 60, 340, 168), 4)


def solder_mask_covers_trace(draw):
    round_rect(draw, (95, 65, 250, 165), 12, fill=MASK)
    pad(draw, (120, 88, 205, 142))
    line(draw, ((255, 115), (455, 115)), TRACE, 12)
    dim_h(draw, 250, 255, 175)
    warn_circle(draw, (230, 88, 285, 143), 4)


def solder_mask_multiple_nets(draw):
    round_rect(draw, (105, 65, 415, 165), 12, fill=MASK)
    pad(draw, (135, 88, 220, 142))
    pad(draw, (300, 88, 385, 142))
    line(draw, ((40, 115), (135, 115)), TRACE, 10)
    line(draw, ((385, 115), (480, 115)), COPPER_DARK, 10)
    warn_circle(draw, (90, 52, 430, 178), 4)


def via_difference_net(draw):
    line(draw, ((35, 125), (485, 125)), TRACE, 12)
    via(draw, 205, 125, 28)
    via(draw, 265, 125, 28)
    dim_h(draw, 205, 265, 78)
    warn_circle(draw, (173, 93, 297, 157), 4)


def via_insmd(draw):
    line(draw, ((35, 135), (220, 135)), TRACE, 12)
    pad(draw, (75, 95, 128, 148), hole=True)
    pad(draw, (142, 95, 198, 148))
    warn_cross(draw, 220, 155, 18)
    line(draw, ((290, 135), (500, 135)), TRACE, 12)
    via(draw, 320, 124, 22, TRACE)
    pad(draw, (350, 96, 470, 148))
    check_mark(draw, 492, 152, 20)


def via_ring(draw):
    via(draw, 175, 118, 36, TRACE)
    ellipse(draw, (150, 82, 200, 154), fill=HOLE)
    via(draw, 350, 118, 36, COPPER)
    ellipse(draw, (326, 82, 374, 154), fill=COPPER_DARK)
    dim_h(draw, 150, 200, 68)
    dim_h(draw, 326, 374, 68)


def via_same_net(draw):
    round_rect(draw, (150, 75, 270, 160), 12, fill=MASK)
    line(draw, ((270, 118), (405, 118)), TRACE, 12)
    via(draw, 175, 118, 26)
    via(draw, 235, 118, 26)
    dim_h(draw, 175, 235, 70)


DRAWERS = {
    "acute_angle": acute_angle,
    "bga": bga,
    "blind2blind": blind2blind,
    "breakage_line": breakage_line,
    "dangling_tracks": dangling_tracks,
    "copper2edge": copper2edge,
    "pth2edge": pth2edge,
    "via2edge": via2edge,
    "npth2edge": npth2edge,
    "grid_spacing": grid_spacing,
    "grid_width": grid_width,
    "hole_density": hole_density,
    "hole_half": hole_half,
    "hole_spuared": hole_spuared,
    "invalid_via": invalid_via,
    "isolated_copper": isolated_copper,
    "line_width": line_width,
    "line2line": line2line,
    "line2pth_inner": line2pth_common,
    "line2pth_outer": line2pth_common,
    "max_diameter": max_diameter,
    "max_diameter_blind_buried": max_diameter_blind_buried,
    "max_slot": max_slot,
    "max_slot_length": max_slot_length,
    "min_diameter": min_diameter,
    "min_slot": min_slot,
    "min_thick_diameter": min_thick_diameter,
    "npth_insmd": lambda draw: pth_np_insmd(draw, npth=True),
    "npth2copper": npth2copper,
    "pad_spacing_base": pad_spacing_base,
    "pad2line": pad2line,
    "pad2pad": pad2pad,
    "pth_difference_net": pth_difference_net,
    "pth_insmd": lambda draw: pth_np_insmd(draw, npth=False),
    "slot_length_width": slot_length_width,
    "smd2edge": smd2edge,
    "soldmask_lack": soldmask_lack,
    "solder_mask_bridge": solder_mask_bridge,
    "solder_mask_covers_trace": solder_mask_covers_trace,
    "solder_mask_multiple_nets": solder_mask_multiple_nets,
    "via_difference_net": via_difference_net,
    "via_insmd": via_insmd,
    "via_ring": via_ring,
    "via_same net": via_same_net,
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, drawer in DRAWERS.items():
        img, draw = canvas()
        drawer(draw)
        save(name, img)
        print(name)


if __name__ == "__main__":
    main()
