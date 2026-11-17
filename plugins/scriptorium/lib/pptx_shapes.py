"""Shared pptx shape walk, used by both pptx-triage and pptx-extract so
their view of a slide's pictures can never drift between them."""

from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.shapes.picture import Picture

# Footer, slide-number and date placeholders are page furniture by
# definition: never body content.
FURNITURE_PLACEHOLDERS = {PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER, PP_PLACEHOLDER.DATE}


def is_furniture_placeholder(shape) -> bool:
    return shape.is_placeholder and shape.placeholder_format.type in FURNITURE_PLACEHOLDERS


def iter_shapes(shapes):
    """Every shape of a slide in z-order, a group's members in place of the
    group (python-pptx yields a group as one shape with no text or image)."""
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from iter_shapes(shape.shapes)
        else:
            yield shape


def is_picture(shape) -> bool:
    """A picture shape or a filled picture placeholder; the latter's
    shape_type is PLACEHOLDER, not PICTURE."""
    return isinstance(shape, Picture)
