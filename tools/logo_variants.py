"""Make the welcome-screen logo for each colour theme from icons/logo.png (the approved Glow - Fork, Graphite).

The logo's glow spans hues ~155 (teal, outer edges) .. ~205 (blue, core). Each theme maps that range onto its own
pair of hues and keeps saturation, value and alpha, so the shape and glow stay exactly the same.

Needs PySide6, which only imports inside Designer: run it through the bridge (sd_execute_python), not standalone.
Writes icons/logo_<theme>.png next to logo.png.
"""
import os
from PySide6.QtGui import QImage, QColor

SRC_LO, SRC_HI = 155.0, 205.0
TARGETS = {                 # theme: (hue for the teal edges, hue for the blue core)
    "designer": (88, 135),  # Designer's lime #99e83f -> green
    "midnight": (200, 250), # sky blue -> indigo
    "ember": (32, -12),     # orange -> pink-red
}

# run via exec there is no __file__: the bridge runner sets ICONS_DIR instead
ICONS = globals().get("ICONS_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "graphpilot", "graphpilot", "icons")

def make(icons):
    src = QImage(os.path.join(icons, "logo.png")).convertToFormat(QImage.Format_ARGB32)
    out = []
    for theme, (a, b) in TARGETS.items():
        im = QImage(src)
        for y in range(im.height()):
            for x in range(im.width()):
                c = im.pixelColor(x, y)
                h = c.hsvHueF() * 360
                if h < 0:   # grey: no hue to move
                    continue
                t = min(1.0, max(0.0, (h - SRC_LO) / (SRC_HI - SRC_LO)))
                nh = (a + (b - a) * t) % 360
                im.setPixelColor(x, y, QColor.fromHsvF(nh / 360, c.hsvSaturationF(), c.valueF(), c.alphaF()))
        path = os.path.join(icons, "logo_%s.png" % theme)
        im.save(path)
        out.append(path)
    return out


result = make(ICONS)
print(result)
