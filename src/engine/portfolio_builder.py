"""
src/engine/portfolio_builder.py
-------------------------------
Core ISO 32000-1 (PDF 1.7) PDF Portfolio Generation Engine.
Uses pure Python pypdf to author interactive /Collection dictionaries,
embedded file streams, metadata schemas, and fallback cover sheets.
"""

import os
import hashlib
import mimetypes
import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Union, BinaryIO, Callable

import pypdf
from pypdf.generic import (
    DictionaryObject,
    ArrayObject,
    NameObject,
    TextStringObject,
    ByteStringObject,
    NumberObject,
    BooleanObject,
    DecodedStreamObject,
)
from pypdf._utils import format_iso8824_date


@dataclass
class SourceFile:
    """Represents a source document embedded inside the portfolio."""
    filepath: Union[str, Path]
    filename: str
    size: int
    file_type: str
    modified_date: datetime.datetime
    description: str = ""
    data: Optional[bytes] = None

    def read_bytes(self) -> bytes:
        if self.data is not None:
            return self.data
        with open(self.filepath, "rb") as f:
            return f.read()


def infer_file_type(extension: str) -> str:
    """Returns a clean user-facing document type label from a file extension."""
    ext = extension.lower()
    mapping = {
        ".pdf": "PDF Document",
        ".docx": "Word Document",
        ".doc": "Word Document (Legacy)",
        ".xlsx": "Excel Spreadsheet",
        ".xls": "Excel Spreadsheet (Legacy)",
        ".csv": "CSV Spreadsheet",
        ".pptx": "PowerPoint Presentation",
        ".ppt": "PowerPoint Presentation (Legacy)",
        ".txt": "Plain Text Document",
        ".png": "PNG Image",
        ".jpg": "JPEG Image",
        ".jpeg": "JPEG Image",
        ".msg": "Outlook Email Message",
        ".eml": "Email Message",
        ".zip": "ZIP Archive",
    }
    return mapping.get(ext, f"{ext.lstrip('.').upper()} File" if ext else "Binary File")


def create_source_file_from_path(filepath: Union[str, Path], description: str = "") -> SourceFile:
    """Constructs a SourceFile instance by inspecting a filesystem path."""
    p = Path(filepath)
    stat = p.stat()
    mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc)
    return SourceFile(
        filepath=p,
        filename=p.name,
        size=stat.st_size,
        file_type=infer_file_type(p.suffix),
        modified_date=mtime,
        description=description,
    )


def build_portfolio(
    output_target: Union[str, Path, BinaryIO],
    files: List[SourceFile],
    title: str = "Document Portfolio",
    subtitle: str = "ISO 32000-1 Interactive Collection",
    organization: str = "Legal & Compliance",
    is_evaluation: bool = True,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> None:
    """
    Constructs an ISO 32000-1 compliant PDF Portfolio containing embedded files and metadata.

    Args:
        output_target: Destination file path or writable binary stream.
        files: List of SourceFile objects to package.
        title: Main title rendered on the fallback Cover Sheet.
        subtitle: Subtitle rendered on the fallback Cover Sheet.
        organization: Author/Organization name displayed on the Cover Sheet.
        is_evaluation: If True, renders an evaluation notice banner on Page 1.
        progress_callback: Optional callback receiving (percentage: int, status_message: str).
    """
    if progress_callback:
        progress_callback(5, "Initializing PDF 1.7 Catalog...")

    writer = pypdf.PdfWriter()

    # 1. Enforce PDF 1.7 Specification (ISO 32000-1 Collections require PDF 1.7)
    writer.pdf_header = "%PDF-1.7"
    writer.root_object[NameObject("/Version")] = NameObject("/1.7")

    # 2. Render Fallback Cover Sheet (Page 1)
    if progress_callback:
        progress_callback(15, "Rendering Fallback Cover Sheet...")

    cover_page = writer.add_blank_page(width=612, height=792)  # Standard US Letter
    font_bold = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
    })
    font_reg = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_oblique = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica-Oblique"),
    })

    cover_page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): writer._add_object(font_bold),
            NameObject("/F2"): writer._add_object(font_reg),
            NameObject("/F3"): writer._add_object(font_oblique),
        })
    })

    # Sanitize text strings for PDF content stream (ASCII Latin-1)
    clean_title = title.replace("(", "[").replace(")", "]")
    clean_subtitle = subtitle.replace("(", "[").replace(")", "]")
    clean_org = organization.replace("(", "[").replace(")", "]")
    date_str = datetime.date.today().isoformat()

    stream_ops = [
        # Top banner background (Navy #1E293B / RGB 0.12, 0.16, 0.23)
        "0.12 0.16 0.23 rg",
        "0 660 612 132 re",
        "f",
        # Banner Typography
        "BT",
        "/F1 22 Tf",
        "1 1 1 rg",
        "50 740 Td",
        f"({clean_title}) Tj",
        "/F2 11 Tf",
        "0 -24 Td",
        f"({clean_subtitle}) Tj",
        "/F3 9 Tf",
        "0 -18 Td",
        f"(Organization: {clean_org} | Date Generated: {date_str}) Tj",
        "ET",
    ]

    # Evaluation Watermark Banner
    if is_evaluation:
        stream_ops.extend([
            # Evaluation Warning Box (Amber #FEF3C7 with border #F59E0B)
            "0.99 0.95 0.78 rg",
            "50 625 512 28 re",
            "f",
            "0.96 0.62 0.04 RG",
            "1.5 w",
            "50 625 512 28 re",
            "S",
            "BT",
            "/F1 9 Tf",
            "0.58 0.32 0.02 rg",
            "60 635 Td",
            "(DEMO / EVALUATION COPY - Created with PDF Portfolio Maker. Register to remove this banner.) Tj",
            "ET",
        ])

    # Instructional Notice Box for Non-Portfolio Readers
    stream_ops.extend([
        "0.96 0.97 0.98 rg",
        "50 455 512 155 re",
        "f",
        "0.82 0.85 0.90 RG",
        "1 w",
        "50 455 512 155 re",
        "S",
        "BT",
        "0.15 0.15 0.15 rg",
        "/F1 12 Tf",
        "70 575 Td",
        "(Interactive PDF Portfolio Notice) Tj",
        "/F2 10 Tf",
        "0 -20 Td",
        "(This document is an interactive ISO 32000-1 standardized PDF Portfolio containing attached) Tj",
        "0 -16 Td",
        "(source files preserved in their original formats with complete metadata and signatures.) Tj",
        "0 -22 Td",
        "(To browse, open, or extract files, view this document in Adobe Acrobat Reader or another) Tj",
        "0 -16 Td",
        "(compliant PDF Portfolio reader.) Tj",
        "0 -20 Td",
        "(In web browser and mobile readers, you can access files via the Attachments / Paperclip tab.) Tj",
        "ET",
    ])

    cs = DecodedStreamObject()
    cs.set_data("\n".join(stream_ops).encode("latin-1", "replace"))
    cover_page[NameObject("/Contents")] = writer._add_object(cs)

    # 3. Define Collection Schema (/CollectionSchema - ISO 32000-1 Table 156)
    if progress_callback:
        progress_callback(30, "Defining Collection Schema...")

    schema = DictionaryObject({
        NameObject("/Type"): NameObject("/CollectionSchema"),
        NameObject("/FileName"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/F"),
            NameObject("/N"): TextStringObject("File Name"),
            NameObject("/O"): NumberObject(0),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/FileSize"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/Size"),
            NameObject("/N"): TextStringObject("Size"),
            NameObject("/O"): NumberObject(1),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/DocType"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/S"),
            NameObject("/N"): TextStringObject("Type"),
            NameObject("/O"): NumberObject(2),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/ModDate"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/ModDate"),
            NameObject("/N"): TextStringObject("Date Modified"),
            NameObject("/O"): NumberObject(3),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/Description"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/Desc"),
            NameObject("/N"): TextStringObject("Description"),
            NameObject("/O"): NumberObject(4),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
    })

    # 4. Construct Collection Dictionary (/Collection - ISO 32000-1 Table 155)
    collection_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/Collection"),
        NameObject("/View"): NameObject("/D"),  # 'D' = Details grid view
        NameObject("/Schema"): schema,
        NameObject("/Sort"): DictionaryObject({
            NameObject("/S"): NameObject("/FileName"),
            NameObject("/A"): BooleanObject(True),
        }),
    })

    writer.root_object[NameObject("/Collection")] = writer._add_object(collection_dict)
    writer.root_object[NameObject("/PageMode")] = NameObject("/UseAttachments")

    # 5. Embed Source Files with Collection Items (/CI - Table 48)
    total_files = len(files)
    for idx, item in enumerate(files):
        if progress_callback:
            pct = 40 + int(50 * (idx + 1) / max(total_files, 1))
            progress_callback(pct, f"Embedding ({idx+1}/{total_files}): {item.filename}")

        file_bytes = item.read_bytes()
        mime = mimetypes.guess_type(item.filename)[0] or "application/octet-stream"

        att = writer.add_attachment(item.filename, file_bytes)
        att.subtype = NameObject(f"/{mime}")
        att.size = NumberObject(len(file_bytes))
        att.checksum = ByteStringObject(hashlib.md5(file_bytes).digest())
        att.modification_date = item.modified_date
        att.description = TextStringObject(item.description)

        # Enhance File Specification Dictionary
        filespec = att.pdf_object
        filespec[NameObject("/UF")] = TextStringObject(item.filename)

        # Link Collection Item Dictionary
        ci_dict = DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionItem"),
            NameObject("/FileName"): TextStringObject(item.filename),
            NameObject("/FileSize"): NumberObject(len(file_bytes)),
            NameObject("/DocType"): TextStringObject(item.file_type),
            NameObject("/ModDate"): TextStringObject(format_iso8824_date(item.modified_date)),
            NameObject("/Description"): TextStringObject(item.description),
        })
        filespec[NameObject("/CI")] = writer._add_object(ci_dict)

    # 6. Final Stream Write
    if progress_callback:
        progress_callback(95, "Serializing PDF Portfolio...")

    if isinstance(output_target, (str, Path)):
        with open(output_target, "wb") as f:
            writer.write(f)
    else:
        writer.write(output_target)

    if progress_callback:
        progress_callback(100, "Done!")
