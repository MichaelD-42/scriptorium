"""Shared pptx shape helpers, used by both pptx-triage and pptx-extract:
slide geometry, hidden shapes, furniture placeholders, the figure rules,
and the figure census (`figure_shapes`) gates.py checks the extractor
against."""

from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.oxml.ns import qn
from pptx.shapes.picture import Picture

# One PDF point is exactly 12700 EMU, so a slide's EMU geometry maps
# straight onto the LibreOffice slide PDF.
EMU_PER_PT = 12700

# Footer, slide-number and date placeholders are page furniture by
# definition: never body content.
FURNITURE_PLACEHOLDERS = {PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER, PP_PLACEHOLDER.DATE}


def is_furniture_placeholder(shape) -> bool:
    return shape.is_placeholder and shape.placeholder_format.type in FURNITURE_PLACEHOLDERS


def is_picture(shape) -> bool:
    """A picture shape or a filled picture placeholder; the latter's
    shape_type is PLACEHOLDER, not PICTURE."""
    return isinstance(shape, Picture)


def is_hidden(shape) -> bool:
    """The shape's own `cNvPr/@hidden` (a group member's flag is its own)."""
    c_nv_pr = shape._element.find(f"./*/{qn('p:cNvPr')}")
    return c_nv_pr is not None and c_nv_pr.get("hidden") in ("1", "true")


# A graphicFrame whose graphicData uri ends in one of these holds a figure:
# an embedded OLE object, a chart, or SmartArt (a plain table is "/table").
FIGURE_FRAME_KINDS = ("ole", "chart", "diagram")
# A shape narrower or shorter than this fraction of the slide is a helper
# (e.g. add-in OLE stubs), not something the slide shows.
DEGENERATE_FRACTION = 0.001


def frame_kind(shape) -> str | None:
    """"ole", "chart" or "diagram" for a figure graphicFrame, else None."""
    data = shape._element.find(f".//{qn('a:graphicData')}") if shape._element.tag == qn("p:graphicFrame") else None
    kind = (data.get("uri") or "").rsplit("/", 1)[-1] if data is not None else ""
    return kind if kind in FIGURE_FRAME_KINDS else None


def is_degenerate(bbox, slide) -> bool:
    """`bbox` (slide EMU) is too thin or too short to show anything."""
    width, height = slide_size(slide)
    return bbox[2] - bbox[0] < DEGENERATE_FRACTION * width or bbox[3] - bbox[1] < DEGENERATE_FRACTION * height


def _is_drawing(el) -> bool:
    """A non-text drawing shape: a connector, a custom geometry, or a preset
    geometry other than `rect` that holds no text."""
    if el.tag == qn("p:cxnSp"):
        return True
    if el.tag != qn("p:sp") or el.find(f"./{qn('p:spPr')}/{qn('a:blipFill')}") is not None:
        return False
    if el.find(f"./{qn('p:spPr')}/{qn('a:custGeom')}") is not None:
        return True
    geometry = el.find(f"./{qn('p:spPr')}/{qn('a:prstGeom')}")
    has_text = any((t.text or "").strip() for t in el.iter(qn("a:t")))
    return geometry is not None and geometry.get("prst") != "rect" and not has_text


def is_figure_group(group) -> bool:
    """A group whose members draw a figure, so the slide PDF's crop of the
    whole group is the figure: at least 2 drawing shapes, or a picture and
    at least 1 drawing shape (arrows, braces or marks over a picture),
    counted at any depth. Its text boxes are text either way."""
    el = group._element
    drawings = sum(1 for member in el.iter(qn("p:sp"), qn("p:cxnSp")) if _is_drawing(member))
    has_picture = next(el.iter(qn("p:pic")), None) is not None
    return drawings >= 2 or (has_picture and drawings >= 1)


def has_picture_fill(shape) -> bool:
    """An autoshape filled with a picture (`spPr/a:blipFill`)."""
    el = shape._element
    return el.tag == qn("p:sp") and el.find(f"./{qn('p:spPr')}/{qn('a:blipFill')}") is not None


def slide_size(slide) -> tuple[int, int]:
    """(width, height) of the slide in EMU."""
    presentation = slide.part.package.presentation_part.presentation
    return presentation.slide_width, presentation.slide_height


def abs_bbox(shape) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) in slide EMU. A group member's offset is in its
    group's child space (`a:chOff`/`a:chExt`), so it is mapped through every
    enclosing group's transform.
    shortcut: rotation and flips are ignored; upgrade if a rotated group's figure crop misses."""
    x, y = shape.left or 0, shape.top or 0
    w, h = shape.width or 0, shape.height or 0
    group = shape._element.getparent()
    while group is not None and group.tag == qn("p:grpSp"):
        xfrm = group.grpSpPr.xfrm
        if xfrm is not None and None not in (xfrm.off, xfrm.ext, xfrm.chOff, xfrm.chExt):
            sx = xfrm.ext.cx / xfrm.chExt.cx if xfrm.chExt.cx else 1.0
            sy = xfrm.ext.cy / xfrm.chExt.cy if xfrm.chExt.cy else 1.0
            x = xfrm.off.x + (x - xfrm.chOff.x) * sx
            y = xfrm.off.y + (y - xfrm.chOff.y) * sy
            w, h = w * sx, h * sy
        group = group.getparent()
    return x, y, x + w, y + h


# A picture showing on less of the slide than this is an icon, not a figure.
MIN_PICTURE_AREA_FRACTION = 0.005


def _visible_area(picture, bbox, width: int, height: int) -> float:
    """The picture's area inside the slide, 0 when its crop leaves nothing."""
    if picture.crop_left + picture.crop_right >= 1 or picture.crop_top + picture.crop_bottom >= 1:
        return 0.0
    w = min(bbox[2], width) - max(bbox[0], 0)
    h = min(bbox[3], height) - max(bbox[1], 0)
    return max(0.0, w) * max(0.0, h)


def figure_shapes(slide) -> list[dict]:
    """The figures the slide shows, read from its shape tree on its own walk
    (not pptx-extract's), so gates.py can check that each got an element.
    One `{shape_id, kind, bbox_emu, groups}` per figure; `groups` are the
    ids of the groups that contain it, outermost first. Kinds:

    - "pic": a picture, at any depth, showing on at least
      MIN_PICTURE_AREA_FRACTION of the slide after its crop;
    - "ole", "chart", "diagram": a figure graphicFrame that is not degenerate;
    - "group": a top-level group that draws a figure (`is_figure_group`);
    - "fill": a shape filled with a picture.

    Hidden shapes, and everything in a hidden group, are left out."""
    width, height = slide_size(slide)
    census = []

    def visit(shapes, groups):
        for shape in shapes:
            if is_hidden(shape):
                continue
            bbox = abs_bbox(shape)
            kind = None
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                kind = "group" if not groups and is_figure_group(shape) else None
            elif is_picture(shape):
                kind = "pic" if _visible_area(shape, bbox, width, height) >= MIN_PICTURE_AREA_FRACTION * width * height else None
            elif frame_kind(shape):
                kind = None if is_degenerate(bbox, slide) else frame_kind(shape)
            elif has_picture_fill(shape):
                kind = "fill"
            if kind:
                census.append({"shape_id": shape.shape_id, "kind": kind, "bbox_emu": [round(v) for v in bbox], "groups": groups})
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                visit(shape.shapes, groups + [shape.shape_id])

    visit(slide.shapes, [])
    return census
