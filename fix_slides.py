#!/usr/bin/env python3
"""
Fix formatting issues in ut_dallas_presentation.pptx.

Problem: Location and House Rules text boxes overlap because Location
has too much text for its 1.50in box, causing visual collision.

Solution: Switch to two-column layout — Location on left, House Rules on right.
Also fixes truncated text where applicable.
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
import copy
import re

INPUT = "/home/liang/.openclaw/workspace/coding/airbnb-ai-agent/ut_dallas_presentation.pptx"
OUTPUT = "/home/liang/.openclaw/workspace/coding/airbnb-ai-agent/ut_dallas_presentation.pptx"  # overwrite in place

prs = Presentation(INPUT)

# Layout constants (inches)
SLIDE_W = 13.33
SLIDE_H = 7.50
MARGIN = 0.60
CONTENT_TOP = 2.20
CONTENT_BOTTOM = 6.90  # leave room for page number at 7.00
CONTENT_H = CONTENT_BOTTOM - CONTENT_TOP  # 4.70in
COL_GAP = 0.30
COL_W = (SLIDE_W - 2 * MARGIN - COL_GAP) / 2  # ~6.07in each

LEFT_COL_LEFT = MARGIN                          # 0.60in
RIGHT_COL_LEFT = MARGIN + COL_W + COL_GAP       # ~6.97in

fixed_count = 0

for idx, slide in enumerate(prs.slides):
    # Identify shapes by text content
    location_shape = None
    rules_shape = None
    page_shape = None

    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        text = shape.text_frame.text.strip()
        if text.startswith("Location") and len(text) > len("Location"):
            location_shape = shape
        elif text.startswith("House Rules"):
            rules_shape = shape
        elif re.match(r'^\d+\s*/\s*\d+$', text):
            page_shape = shape

    if not location_shape and not rules_shape:
        continue

    # Case 1: Both Location and House Rules -> two-column layout
    if location_shape and rules_shape:
        # Location -> left column
        location_shape.left = Inches(LEFT_COL_LEFT)
        location_shape.top = Inches(CONTENT_TOP)
        location_shape.width = Inches(COL_W)
        location_shape.height = Inches(CONTENT_H)

        # House Rules -> right column
        rules_shape.left = Inches(RIGHT_COL_LEFT)
        rules_shape.top = Inches(CONTENT_TOP)
        rules_shape.width = Inches(COL_W)
        rules_shape.height = Inches(CONTENT_H)

        fixed_count += 1
        print(f"  Slide {idx+1}: two-column layout (Location left, House Rules right)")

    # Case 2: Only House Rules (no Location) -> keep full width, already fine
    elif rules_shape and not location_shape:
        # These slides (hotels) already have full-width House Rules - no change needed
        pass

    # Fix truncated text in Location
    if location_shape:
        for para in location_shape.text_frame.paragraphs:
            for run in para.runs:
                if run.text.endswith("are the bes"):
                    run.text = run.text.replace("are the bes", "are the best options for getting around.")
                    print(f"  Slide {idx+1}: fixed truncated 'Uber/Lyft' text")

print(f"\nFixed {fixed_count} slides with two-column layout.")
prs.save(OUTPUT)
print(f"Saved to {OUTPUT}")
