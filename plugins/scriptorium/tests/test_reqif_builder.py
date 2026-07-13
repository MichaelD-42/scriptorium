"""Unit tests for assemble-output/scripts/reqif_builder.py -- ReqIF XML
generation, exercised on hand-built doc_data (no filesystem)."""

from xml.etree import ElementTree as ET

from conftest import load_script

reqif_builder = load_script("assemble-output/scripts/reqif_builder.py", "reqif_builder_module")

NS = {"r": reqif_builder.REQIF_NS, "x": reqif_builder.XHTML_NS}


def _doc_data(*elements: dict) -> dict:
    return {"doc": "sample", "pages": {1: {"page_number": 1, "elements": list(elements)}}}


class TestBuildReqifXml:
    def test_well_formed_with_req_if_root(self):
        xml_text = reqif_builder.build_reqif_xml("sample", _doc_data({"type": "paragraph", "text": "hi"}))
        root = ET.fromstring(xml_text)
        assert root.tag == reqif_builder._q("REQ-IF")

    def test_spec_object_count_matches_element_count(self):
        elements = [
            {"type": "heading", "level": 1, "text": "Intro"},
            {"type": "paragraph", "text": "body text"},
            {"type": "table", "rows": [["a", "b"]]},
        ]
        xml_text = reqif_builder.build_reqif_xml("sample", _doc_data(*elements))
        root = ET.fromstring(xml_text)
        spec_objects = root.findall(".//r:SPEC-OBJECT", NS)
        assert len(spec_objects) == len(elements)

    def test_heading_hierarchy_nests_by_level(self):
        elements = [
            {"type": "heading", "level": 1, "text": "Chapter 1"},
            {"type": "paragraph", "text": "para under chapter 1"},
            {"type": "heading", "level": 2, "text": "Section 1.1"},
            {"type": "paragraph", "text": "para under section 1.1"},
            {"type": "heading", "level": 1, "text": "Chapter 2"},
        ]
        xml_text = reqif_builder.build_reqif_xml("sample", _doc_data(*elements))
        root = ET.fromstring(xml_text)

        specification = root.find(".//r:SPECIFICATIONS/r:SPECIFICATION", NS)
        top_level = specification.find("r:CHILDREN", NS).findall("r:SPEC-HIERARCHY", NS)
        # Chapter 1 and Chapter 2 are siblings at the top level -- Section
        # 1.1 nests inside Chapter 1's own CHILDREN, not at this level.
        assert len(top_level) == 2

        chapter1_children = top_level[0].find("r:CHILDREN", NS)
        assert chapter1_children is not None
        # para (attached before the nested heading) + Section 1.1 heading.
        assert len(chapter1_children.findall("r:SPEC-HIERARCHY", NS)) == 2

    def test_image_xhtml_includes_mermaid_pre_and_object(self):
        el = {"type": "image", "asset": "assets/a.png", "caption": "cap", "mermaid": "flowchart TD\n  A --> B"}
        xhtml_div = reqif_builder._image_xhtml(el)
        pre = xhtml_div.find(f"{{{reqif_builder.XHTML_NS}}}pre")
        obj = xhtml_div.find(f"{{{reqif_builder.XHTML_NS}}}object")
        assert pre.text == "flowchart TD\n  A --> B"
        assert obj.get("data") == "assets/a.png"
        assert obj.text == "cap"

    def test_image_xhtml_without_mermaid_has_no_pre(self):
        el = {"type": "image", "asset": "assets/a.png", "caption": ""}
        xhtml_div = reqif_builder._image_xhtml(el)
        assert xhtml_div.find(f"{{{reqif_builder.XHTML_NS}}}pre") is None


class TestWriteReqifz:
    def test_zip_contains_reqif_and_referenced_assets(self, tmp_path, monkeypatch):
        import zipfile

        monkeypatch.chdir(tmp_path)
        output_dir = tmp_path / "output" / "sample"
        assets_dir = output_dir / "assets"
        assets_dir.mkdir(parents=True)
        (assets_dir / "a.png").write_bytes(b"fake-png-bytes")

        doc_data = _doc_data({"type": "image", "asset": "assets/a.png", "caption": ""})
        reqif_xml = reqif_builder.build_reqif_xml("sample", doc_data)
        zip_path = reqif_builder.write_reqifz("sample", doc_data, reqif_xml)

        assert zip_path.name == "sample.reqifz"
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "sample.reqif" in names
            assert "assets/a.png" in names

    def test_missing_asset_on_disk_is_skipped_not_erroring(self, tmp_path, monkeypatch):
        import zipfile

        monkeypatch.chdir(tmp_path)
        (tmp_path / "output" / "sample").mkdir(parents=True)

        doc_data = _doc_data({"type": "image", "asset": "assets/missing.png", "caption": ""})
        reqif_xml = reqif_builder.build_reqif_xml("sample", doc_data)
        zip_path = reqif_builder.write_reqifz("sample", doc_data, reqif_xml)

        with zipfile.ZipFile(zip_path) as zf:
            assert zf.namelist() == ["sample.reqif"]
