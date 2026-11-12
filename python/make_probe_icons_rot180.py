#!/usr/bin/env python3
"""Build probe icons for a machine whose X+ points left and Y+ points down on the screen.

The Versa Probe screen is drawn for X+ to the right and Y+ up. Turned 180 degrees, the picture
for X+Y+ is the stock X-Y- picture, so each icon here is its opposite stock icon with only the
+/- signs of the label swapped (text stays upright). Skew icons have no text and are just turned.
Run once; writes into qtvcp/images/probe_icons_rot180. Used by qtdragon_hd_handler.rotate_probe_screen().
"""
import os
from PIL import Image

SRC = '/usr/share/qtvcp/images/probe_icons'
DST = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'qtvcp', 'images', 'probe_icons_rot180')

def components(im, thr=60):
    w, h = im.size; px = im.load(); seen = set(); out = []
    for y in range(h):
        for x in range(w):
            if (x, y) in seen or px[x, y][3] < thr:
                continue
            st = [(x, y)]; seen.add((x, y)); xs = []; ys = []
            while st:
                cx, cy = st.pop(); xs.append(cx); ys.append(cy)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and px[nx, ny][3] >= thr:
                            seen.add((nx, ny)); st.append((nx, ny))
            out.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
    return out

def kind(b):
    w, h = b[2] - b[0], b[3] - b[1]
    if 8 <= w <= 13 and 3 <= h <= 6:
        return '-'
    if 9 <= w <= 13 and 9 <= h <= 13:
        return '+'
    return None

def load(n):
    return Image.open(os.path.join(SRC, n + '.png')).convert('RGBA')

def glyph(name, sign):
    im = load(name)
    b = [c for c in components(im) if kind(c) == sign][0]
    return im.crop((b[0] - 1, b[1] - 1, b[2] + 1, b[3] + 1))

PLUS, MINUS = glyph('X+Y+', '+'), glyph('X-Y-', '-')

def swap_signs(im):
    im = im.copy()
    for b in components(im):
        k = kind(b)
        if not k:
            continue
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        im.paste((0, 0, 0, 0), (b[0] - 1, b[1] - 1, b[2] + 1, b[3] + 1))
        g = MINUS if k == '+' else PLUS
        im.alpha_composite(g, (max(0, min(im.width - g.width, cx - g.width // 2)),
                               max(0, min(im.height - g.height, cy - g.height // 2))))
    return im

def opposite(n):
    return n.replace('+', '#').replace('-', '+').replace('#', '-')

def main():
    os.makedirs(DST, exist_ok=True)
    for pre in ('', 'in'):
        for n in ('X+Y+', 'X+Y-', 'X-Y+', 'X-Y-', 'X+', 'X-', 'Y+', 'Y-'):
            swap_signs(load(pre + opposite(n))).save(os.path.join(DST, pre + n + '.png'))
    for n in ('angleX+', 'angleX-', 'angleY+', 'angleY-'):
        load(n).rotate(180).save(os.path.join(DST, n + '.png'))

if __name__ == '__main__':
    main()
