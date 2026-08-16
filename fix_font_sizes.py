#!/usr/bin/env python3
"""Set appropriate font sizes on Location/House Rules text boxes."""
from pptx import Presentation
from pptx.util import Pt
from pptx.oxml.ns import qn

PPTX = "/home/liang/.openclaw/workspace/coding/airbnb-ai-agent/ut_dallas_presentation.pptx"
prs = Presentation(PPTX)

for idx, slide in enumerate(prs.slides):
    if idx < 2:
        continue

    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        text = shape.text_frame.text.strip()
        if not (text.startswith("Location") or text.startswith("House Rules")):
            continue

        # Count body lines (paragraphs minus header)
        paras = list(shape.text_frame.paragraphs)
        body_count = len(paras) - 1

        # Determine font size based on content volume
        if body_count > 20:
            body_size = Pt(8)
            header_size = Pt(12)
        elif body_count > 12:
            body_size = Pt(9)
            header_size = Pt(13)
        elif body_count > 6:
            body_size = Pt(10)
            header_size = Pt(14)
        else:
            body_size = Pt(11)
            header_size = Pt(14)

        for pj, para in enumerate(paras):
            sz = header_size if pj == 0 else body_size
            for run in para.runs:
                run.font.size = sz
            if not para.runs:
                # Set on paragraph level if no runs
                from pptx.text.text import _Paragraph
                run = para.add_run()
                run.font.size = sz

        print(f"  Slide {idx+1}: {text[:15]}... body_count={body_count} -> body_size={sz}")

prs.save(PPTX)
print(f"\nSaved.")
