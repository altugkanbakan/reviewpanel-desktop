"""
Tests for manuscript discovery and reading (manuscript.py).

Guards:
  * discover_manuscript reads .md / .txt / .tex and extracts titles.
  * Unreadable input surfaces as ValueError, not a crash or silent junk.
  * read_tex_recursive resolves \\input/\\include and terminates on
    cyclic includes (regression: infinite recursion).
  * read_docx raises ValueError on a corrupt file, reads a real one.
"""

import pytest

from manuscript import discover_manuscript, read_docx, read_tex_recursive


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
