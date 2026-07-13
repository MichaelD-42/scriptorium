#!/usr/bin/env python3
"""Build a ReqIF (OMG Requirements Interchange Format) document from merged
elements.json, and optionally package it into a .reqifz archive. See
SKILL.md's "ReqIF format" section for the element -> SPEC-OBJECT mapping and
the heading-hierarchy rule.

Schema: http://www.omg.org/spec/ReqIF/20110401/reqif.xsd — unchanged across
ReqIF 1.0.1/1.1/1.2 (only the spec *text* changed between those versions,
not the XML schema or underlying model).

Built with stdlib xml.etree.ElementTree, not string concatenation — it
handles namespaces and XML-escaping correctly, and this skill has no other
reason to take on a templating dependency for XML.
"""

import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import paths  # noqa: E402

REQIF_NS = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
XHTML_NS = "http://www.w3.org/1999/xhtml"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# Fixed identifiers for the one SPEC-OBJECT-TYPE / two ATTRIBUTE-DEFINITIONs
# / two DATATYPE-DEFINITIONs / one SPECIFICATION-TYPE every generated
# document reuses — there's only ever one "kind" of extracted element type
# in this pipeline's model, so these don't need to be per-document unique.
SPEC_OBJECT_TYPE_ID = "scriptorium-spec-object-type"
CHAPTER_NAME_ATTR_ID = "scriptorium-attr-chapter-name"
TEXT_ATTR_ID = "scriptorium-attr-text"
STRING_DATATYPE_ID = "scriptorium-datatype-string"
XHTML_DATATYPE_ID = "scriptorium-datatype-xhtml"
SPECIFICATION_TYPE_ID = "scriptorium-specification-type"


def _q(tag: str) -> str:
    return f"{{{REQIF_NS}}}{tag}"


def _uid() -> str:
    # ReqIF IDENTIFIERs must be valid xsd:ID (can't start with a digit) —
    # a bare uuid4 hex can, so prefix it.
    return f"_{uuid.uuid4()}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sorted_pages(doc_data: dict) -> list[dict]:
    return sorted(doc_data["pages"].values(), key=lambda p: p["page_number"])


def _flatten_elements(doc_data: dict) -> list[dict]:
    return [el for page in _sorted_pages(doc_data) for el in page["elements"]]


# --- XHTML fragment builders (all wrapped in the required xhtml:div) -------

def _xhtml_div(*children: ET.Element) -> ET.Element:
    div = ET.Element(f"{{{XHTML_NS}}}div")
    div.extend(children)
    return div


def _paragraph_xhtml(text: str) -> ET.Element:
    p = ET.Element(f"{{{XHTML_NS}}}p")
    p.text = text
    return _xhtml_div(p)


def _table_xhtml(rows: list[list[str]]) -> ET.Element:
    table = ET.Element(f"{{{XHTML_NS}}}table")
    for row in rows:
        tr = ET.SubElement(table, f"{{{XHTML_NS}}}tr")
        for cell in row:
            td = ET.SubElement(tr, f"{{{XHTML_NS}}}td")
            td.text = str(cell)
    return _xhtml_div(table)


def _image_xhtml(el: dict) -> ET.Element:
    children = []
    if el.get("mermaid"):
        pre = ET.Element(f"{{{XHTML_NS}}}pre")
        pre.text = el["mermaid"]
        children.append(pre)
    obj = ET.Element(f"{{{XHTML_NS}}}object")
    obj.set("data", el["asset"])
    obj.set("type", "image/png")
    obj.text = el.get("caption") or ""
    children.append(obj)
    return _xhtml_div(*children)


# --- SPEC-OBJECT attribute values -------------------------------------------

def _add_string_value(values_el: ET.Element, attr_id: str, text: str) -> None:
    val = ET.SubElement(values_el, _q("ATTRIBUTE-VALUE-STRING"))
    val.set("THE-VALUE", text)
    definition = ET.SubElement(val, _q("DEFINITION"))
    ET.SubElement(definition, _q("ATTRIBUTE-DEFINITION-STRING-REF")).text = attr_id


def _add_xhtml_value(values_el: ET.Element, attr_id: str, xhtml_div_el: ET.Element) -> None:
    val = ET.SubElement(values_el, _q("ATTRIBUTE-VALUE-XHTML"))
    definition = ET.SubElement(val, _q("DEFINITION"))
    ET.SubElement(definition, _q("ATTRIBUTE-DEFINITION-XHTML-REF")).text = attr_id
    the_value = ET.SubElement(val, _q("THE-VALUE"))
    the_value.append(xhtml_div_el)


# --- document assembly ------------------------------------------------------

def _build_header(root: ET.Element, doc: str, now: str) -> None:
    the_header = ET.SubElement(root, _q("THE-HEADER"))
    header = ET.SubElement(the_header, _q("REQ-IF-HEADER"))
    header.set("IDENTIFIER", _uid())
    ET.SubElement(header, _q("CREATION-TIME")).text = now
    ET.SubElement(header, _q("REQ-IF-TOOL-ID")).text = "Scriptorium"
    ET.SubElement(header, _q("REQ-IF-VERSION")).text = "1.0"
    ET.SubElement(header, _q("SOURCE-TOOL-ID")).text = "Scriptorium"
    ET.SubElement(header, _q("TITLE")).text = doc


def _build_datatypes(content: ET.Element, now: str) -> None:
    datatypes = ET.SubElement(content, _q("DATATYPES"))
    string_dt = ET.SubElement(datatypes, _q("DATATYPE-DEFINITION-STRING"))
    string_dt.set("IDENTIFIER", STRING_DATATYPE_ID)
    string_dt.set("LONG-NAME", "String")
    string_dt.set("LAST-CHANGE", now)
    string_dt.set("MAX-LENGTH", "4000")
    xhtml_dt = ET.SubElement(datatypes, _q("DATATYPE-DEFINITION-XHTML"))
    xhtml_dt.set("IDENTIFIER", XHTML_DATATYPE_ID)
    xhtml_dt.set("LONG-NAME", "XHTML")
    xhtml_dt.set("LAST-CHANGE", now)


def _build_spec_types(content: ET.Element, now: str) -> None:
    spec_types = ET.SubElement(content, _q("SPEC-TYPES"))

    spec_object_type = ET.SubElement(spec_types, _q("SPEC-OBJECT-TYPE"))
    spec_object_type.set("IDENTIFIER", SPEC_OBJECT_TYPE_ID)
    spec_object_type.set("LONG-NAME", "Scriptorium Extracted Element")
    spec_object_type.set("LAST-CHANGE", now)
    spec_attributes = ET.SubElement(spec_object_type, _q("SPEC-ATTRIBUTES"))

    chapter_attr = ET.SubElement(spec_attributes, _q("ATTRIBUTE-DEFINITION-STRING"))
    chapter_attr.set("IDENTIFIER", CHAPTER_NAME_ATTR_ID)
    chapter_attr.set("LONG-NAME", "ReqIF.ChapterName")
    chapter_attr.set("LAST-CHANGE", now)
    chapter_type = ET.SubElement(chapter_attr, _q("TYPE"))
    ET.SubElement(chapter_type, _q("DATATYPE-DEFINITION-STRING-REF")).text = STRING_DATATYPE_ID

    text_attr = ET.SubElement(spec_attributes, _q("ATTRIBUTE-DEFINITION-XHTML"))
    text_attr.set("IDENTIFIER", TEXT_ATTR_ID)
    text_attr.set("LONG-NAME", "ReqIF.Text")
    text_attr.set("LAST-CHANGE", now)
    text_type = ET.SubElement(text_attr, _q("TYPE"))
    ET.SubElement(text_type, _q("DATATYPE-DEFINITION-XHTML-REF")).text = XHTML_DATATYPE_ID

    specification_type = ET.SubElement(spec_types, _q("SPECIFICATION-TYPE"))
    specification_type.set("IDENTIFIER", SPECIFICATION_TYPE_ID)
    specification_type.set("LONG-NAME", "Scriptorium Document")
    specification_type.set("LAST-CHANGE", now)


def _build_spec_objects_and_hierarchy(content: ET.Element, doc: str, doc_data: dict, now: str) -> None:
    spec_objects_el = ET.SubElement(content, _q("SPEC-OBJECTS"))

    specifications = ET.SubElement(content, _q("SPECIFICATIONS"))
    specification = ET.SubElement(specifications, _q("SPECIFICATION"))
    specification.set("IDENTIFIER", _uid())
    specification.set("LONG-NAME", doc)
    specification.set("LAST-CHANGE", now)
    spec_type_ref = ET.SubElement(specification, _q("TYPE"))
    ET.SubElement(spec_type_ref, _q("SPECIFICATION-TYPE-REF")).text = SPECIFICATION_TYPE_ID

    # CHILDREN elements are created lazily (only once a first child actually
    # exists) — the schema requires a present CHILDREN to contain at least
    # one SPEC-HIERARCHY, so an eagerly-created empty one on a leaf heading
    # would be invalid.
    children_cache: dict[int, ET.Element] = {}

    def children_of(node: ET.Element) -> ET.Element:
        key = id(node)
        if key not in children_cache:
            children_cache[key] = ET.SubElement(node, _q("CHILDREN"))
        return children_cache[key]

    heading_stack: list[tuple[int, ET.Element]] = []  # (level, SPEC-HIERARCHY node)

    for el in _flatten_elements(doc_data):
        obj_id = _uid()
        spec_object = ET.SubElement(spec_objects_el, _q("SPEC-OBJECT"))
        spec_object.set("IDENTIFIER", obj_id)
        spec_object.set("LAST-CHANGE", now)
        obj_type = ET.SubElement(spec_object, _q("TYPE"))
        ET.SubElement(obj_type, _q("SPEC-OBJECT-TYPE-REF")).text = SPEC_OBJECT_TYPE_ID
        values = ET.SubElement(spec_object, _q("VALUES"))

        level = None
        if el["type"] == "heading":
            level = el["level"]
            spec_object.set("LONG-NAME", el["text"][:100])
            _add_string_value(values, CHAPTER_NAME_ATTR_ID, el["text"])
        elif el["type"] == "paragraph":
            spec_object.set("LONG-NAME", "Paragraph")
            _add_xhtml_value(values, TEXT_ATTR_ID, _paragraph_xhtml(el["text"]))
        elif el["type"] == "table":
            spec_object.set("LONG-NAME", "Table")
            _add_xhtml_value(values, TEXT_ATTR_ID, _table_xhtml(el["rows"]))
        elif el["type"] == "image":
            spec_object.set("LONG-NAME", (el.get("caption") or "Image")[:100])
            _add_xhtml_value(values, TEXT_ATTR_ID, _image_xhtml(el))

        # Headings build the hierarchy: pop back to the nearest ancestor
        # (level < this heading's level), attach under it (or the document
        # root if there's no such ancestor yet).
        if level is not None:
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
        parent_node = heading_stack[-1][1] if heading_stack else specification

        hierarchy_node = ET.SubElement(children_of(parent_node), _q("SPEC-HIERARCHY"))
        hierarchy_node.set("IDENTIFIER", _uid())
        hierarchy_node.set("LAST-CHANGE", now)
        object_ref = ET.SubElement(hierarchy_node, _q("OBJECT"))
        ET.SubElement(object_ref, _q("SPEC-OBJECT-REF")).text = obj_id

        if level is not None:
            heading_stack.append((level, hierarchy_node))


def build_reqif_xml(doc: str, doc_data: dict) -> str:
    ET.register_namespace("", REQIF_NS)
    ET.register_namespace("xhtml", XHTML_NS)
    ET.register_namespace("xsi", XSI_NS)

    now = _now()
    root = ET.Element(_q("REQ-IF"))
    root.set(f"{{{XSI_NS}}}schemaLocation", f"{REQIF_NS} {REQIF_NS}")

    _build_header(root, doc, now)

    core_content = ET.SubElement(root, _q("CORE-CONTENT"))
    content = ET.SubElement(core_content, _q("REQ-IF-CONTENT"))
    _build_datatypes(content, now)
    _build_spec_types(content, now)
    _build_spec_objects_and_hierarchy(content, doc, doc_data, now)

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def write_reqifz(doc: str, doc_data: dict, reqif_xml: str) -> Path:
    """Package <doc>.reqif plus every image asset it references into
    output/<doc>/<doc>.reqifz — the .reqif sits at the archive root and
    assets keep their relative asset path, so the XHTML object refs
    (`data="assets/..."`) resolve the same way inside the archive as they
    do on disk."""
    output_dir = paths.output_dir(doc)
    asset_paths = sorted({
        el["asset"]
        for page in _sorted_pages(doc_data)
        for el in page["elements"]
        if el["type"] == "image"
    })

    zip_path = paths.output_file(doc, "reqifz")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{doc}.reqif", reqif_xml)
        for asset in asset_paths:
            asset_path = output_dir / asset
            if asset_path.exists():
                zf.write(asset_path, arcname=asset)
    return zip_path
