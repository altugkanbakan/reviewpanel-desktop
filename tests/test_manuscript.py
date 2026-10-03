"""
Tests for manuscript discovery and reading (manuscript.py).

Guards:
  * discover_manuscript reads .md / .txt / .tex and extracts titles.
  * Unreadable input surfaces as ValueError, not a crash or silent junk.
  * read_tex_recursive resolves \\input/\\include and terminates on
    cyclic includes (regression: infinite recursion).
  * read_docx raises ValueError on a corrupt file, reads a real one.
  * MarkItDown keeps .docx tables as Markdown and reads text-based .pdf;
    python-docx remains the fallback.
"""

import pytest

from manuscript import discover_manuscript, read_docx, read_pdf, read_tex_recursive


class TestDiscoverManuscript:
    def test_reads_markdown_with_title(self, tmp_path):
        f = tmp_path / "paper.md"
        f.write_text(
            "# A Great Title\n\nIntroduction text.", encoding="utf-8"
        )
        data = discover_manuscript(str(f))
        assert data["title"] == "A Great Title"
        assert "Introduction text." in data["full_text"]
        assert data["source_path"] == str(f)

    def test_reads_txt_title_falls_back_to_stem(self, tmp_path):
        f = tmp_path / "plain_notes.txt"
        f.write_text("Just body text, no heading.", encoding="utf-8")
        data = discover_manuscript(str(f))
        assert data["full_text"] == "Just body text, no heading."
        assert data["title"] == "plain_notes"

    def test_reads_tex_with_title(self, tmp_path):
        f = tmp_path / "paper.tex"
        f.write_text(
            "\\documentclass{article}\n\\title{Latex Title}\n"
            "\\begin{document}\nBody.\n\\end{document}\n",
            encoding="utf-8",
        )
        data = discover_manuscript(str(f))
        assert data["title"] == "Latex Title"
        assert "Body." in data["full_text"]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            discover_manuscript(str(tmp_path / "nope.md"))

    def test_unreadable_input_raises_value_error(self, tmp_path):
        # A directory masquerading as a .md file: exists, cannot be read.
        d = tmp_path / "fake.md"
        d.mkdir()
        with pytest.raises(ValueError):
            discover_manuscript(str(d))

    def test_corrupt_docx_raises_value_error(self, tmp_path):
        f = tmp_path / "broken.docx"
        f.write_bytes(b"this is definitely not a zip/docx file")
        with pytest.raises(ValueError):
            discover_manuscript(str(f))


class TestReadTexRecursive:
    def test_resolves_input_and_include(self, tmp_path):
        (tmp_path / "intro.tex").write_text(
            "Intro section text.", encoding="utf-8"
        )
        (tmp_path / "methods.tex").write_text(
            "Methods section text.", encoding="utf-8"
        )
        main = tmp_path / "main.tex"
        main.write_text(
            "Start.\n\\input{intro}\n\\include{methods.tex}\nEnd.",
            encoding="utf-8",
        )
        text = read_tex_recursive(main)
        assert "Intro section text." in text
        assert "Methods section text." in text
        assert "Start." in text and "End." in text

    def test_unresolvable_include_left_verbatim(self, tmp_path):
        main = tmp_path / "main.tex"
        main.write_text("\\input{missing_file}\n", encoding="utf-8")
        text = read_tex_recursive(main)
        assert "\\input{missing_file}" in text

    def test_cyclic_include_terminates(self, tmp_path):
        (tmp_path / "a.tex").write_text(
            "A body.\n\\input{b}", encoding="utf-8"
        )
        (tmp_path / "b.tex").write_text(
            "B body.\n\\input{a}", encoding="utf-8"
        )
        text = read_tex_recursive(tmp_path / "a.tex")  # must not recurse forever
        assert "A body." in text
        assert "B body." in text
        # The cycle is broken: each file's body appears exactly once
        assert text.count("A body.") == 1
        assert text.count("B body.") == 1


class TestReadDocx:
    def test_corrupt_docx_raises_value_error(self, tmp_path):
        f = tmp_path / "corrupt.docx"
        f.write_bytes(b"\x00\x01\x02 not a word document")
        with pytest.raises(ValueError):
            read_docx(f)

    def test_reads_valid_docx(self, tmp_path):
        docx = pytest.importorskip("docx")
        doc = docx.Document()
        doc.add_paragraph("First paragraph.")
        doc.add_paragraph("Second paragraph.")
        path = tmp_path / "valid.docx"
        doc.save(str(path))
        text = read_docx(path)
        assert "First paragraph." in text
        assert "Second paragraph." in text


def _minimal_pdf(text: str) -> bytes:
    """A tiny single-page, text-based PDF (no reportlab needed)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, xref
    )
    return bytes(out)


class TestMarkItDown:
    """MarkItDown path: tables survive as Markdown, PDFs are readable, and
    the python-docx fallback still works when MarkItDown is unavailable."""

    def test_docx_table_kept_as_markdown(self, tmp_path):
        pytest.importorskip("markitdown")
        docx = pytest.importorskip("docx")
        doc = docx.Document()
        doc.add_paragraph("Baseline data follow.")
        table = doc.add_table(rows=2, cols=2)
        for i, row in enumerate([["Age", "54.2"], ["Male %", "61"]]):
            for j, value in enumerate(row):
                table.cell(i, j).text = value
        path = tmp_path / "tables.docx"
        doc.save(str(path))
        text = read_docx(path)
        assert "| Age | 54.2 |" in text

    def test_docx_falls_back_to_python_docx(self, tmp_path, monkeypatch):
        docx = pytest.importorskip("docx")
        import manuscript
        monkeypatch.setattr(manuscript, "_get_markitdown", lambda: None)
        doc = docx.Document()
        doc.add_paragraph("Fallback paragraph.")
        path = tmp_path / "fallback.docx"
        doc.save(str(path))
        assert "Fallback paragraph." in read_docx(path)

    def test_docx_title_uses_stem_not_first_section(self, tmp_path):
        pytest.importorskip("markitdown")
        docx = pytest.importorskip("docx")
        doc = docx.Document()
        doc.add_heading("Methods", 1)
        doc.add_paragraph("We enrolled patients.")
        path = tmp_path / "my_study.docx"
        doc.save(str(path))
        assert discover_manuscript(str(path))["title"] == "my_study"

    def test_reads_text_pdf(self, tmp_path):
        pytest.importorskip("markitdown")
        path = tmp_path / "paper.pdf"
        path.write_bytes(_minimal_pdf("Hello manuscript PDF"))
        data = discover_manuscript(str(path))
        assert "Hello manuscript PDF" in data["full_text"]
        # The manuscript PDF itself is not listed as a figure
        assert str(path.resolve()) not in data["figure_files"]

    def test_unreadable_pdf_raises_value_error(self, tmp_path):
        pytest.importorskip("markitdown")
        path = tmp_path / "broken.pdf"
        path.write_bytes(b"%PDF-1.4 not really a pdf")
        with pytest.raises(ValueError):
            read_pdf(path)

    def test_pdf_without_markitdown_raises_import_error(self, tmp_path, monkeypatch):
        import manuscript
        monkeypatch.setattr(manuscript, "_get_markitdown", lambda: None)
        path = tmp_path / "paper.pdf"
        path.write_bytes(_minimal_pdf("x"))
        with pytest.raises(ImportError):
            read_pdf(path)
