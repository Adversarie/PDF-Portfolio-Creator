"""
src/engine/portfolio_builder.py
-------------------------------
Core ISO 32000-1 (PDF 1.7) PDF Portfolio Generation Engine.
Uses pure Python pypdf to author interactive /Collection dictionaries,
embedded file streams, metadata schemas, and fallback cover sheets.
"""

import os
import io
import re
import zlib
import email
import email.policy
import mailbox
import hashlib
import mimetypes
import datetime
from pathlib import Path
from dataclasses import dataclass
from contextlib import contextmanager
from typing import List, Optional, Union, BinaryIO, Callable, Iterator, Tuple, Dict

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
    EncodedStreamObject,
)
from pypdf._utils import format_iso8824_date

STREAM_CHUNK_SIZE = 1024 * 1024  # 1 MB streaming chunk size for constant-RAM processing


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
    folder: str = ""
    bates_number: str = ""
    sha256: str = ""

    def iter_chunks(self, chunk_size: int = STREAM_CHUNK_SIZE) -> Iterator[bytes]:
        """
        Streams the Source File in fixed-size byte chunks (default 1 MB)
        to avoid loading multi-gigabyte files into RAM all at once.
        """
        if self.data is not None:
            view = memoryview(self.data)
            for offset in range(0, len(view), chunk_size):
                yield bytes(view[offset : offset + chunk_size])
            return

        with open(self.filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    @contextmanager
    def open_stream(self) -> Iterator[BinaryIO]:
        """Opens a readable binary stream for the Source File without full eager buffering."""
        if self.data is not None:
            stream = io.BytesIO(self.data)
            try:
                yield stream
            finally:
                stream.close()
        else:
            with open(self.filepath, "rb") as f:
                yield f

    def compute_digests(self, chunk_size: int = STREAM_CHUNK_SIZE) -> Tuple[bytes, str, int]:
        """
        Computes (md5_raw_digest, sha256_hex_digest, byte_length) in a single
        streaming pass over fixed-size chunks (O(1) memory overhead).
        """
        md5_hasher = hashlib.md5()
        sha256_hasher = hashlib.sha256()
        total_bytes = 0
        for chunk in self.iter_chunks(chunk_size=chunk_size):
            md5_hasher.update(chunk)
            sha256_hasher.update(chunk)
            total_bytes += len(chunk)
        sha_hex = sha256_hasher.hexdigest()
        self.sha256 = sha_hex
        return md5_hasher.digest(), sha_hex, total_bytes

    def compute_sha256(self, chunk_size: int = STREAM_CHUNK_SIZE) -> str:
        """Returns the hex-encoded SHA-256 digest of the Source File using chunked streaming."""
        if self.sha256:
            return self.sha256
        _, sha_hex, _ = self.compute_digests(chunk_size=chunk_size)
        return sha_hex

    def compress_and_hash_stream(self, chunk_size: int = STREAM_CHUNK_SIZE) -> Tuple[bytes, bytes, str, int]:
        """
        Streams the Source File in 1 MB chunks through zlib deflate compression,
        MD5, and SHA-256 simultaneously so uncompressed multi-hundred-MB files
        never need to reside in memory all at once.
        Returns (compressed_flate_bytes, md5_digest_bytes, sha256_hex, raw_size).
        """
        compressor = zlib.compressobj(level=zlib.Z_DEFAULT_COMPRESSION)
        md5_hasher = hashlib.md5()
        sha256_hasher = hashlib.sha256()
        compressed_parts: List[bytes] = []
        raw_size = 0

        for chunk in self.iter_chunks(chunk_size=chunk_size):
            raw_size += len(chunk)
            md5_hasher.update(chunk)
            sha256_hasher.update(chunk)
            comp = compressor.compress(chunk)
            if comp:
                compressed_parts.append(comp)

        tail = compressor.flush()
        if tail:
            compressed_parts.append(tail)

        sha_hex = sha256_hasher.hexdigest()
        self.sha256 = sha_hex
        return b"".join(compressed_parts), md5_hasher.digest(), sha_hex, raw_size

    def read_bytes(self) -> bytes:
        """Returns raw file bytes (retained for compatibility and small file extraction)."""
        if self.data is not None:
            return self.data
        with open(self.filepath, "rb") as f:
            return f.read()


@dataclass
class PortfolioManifest:
    """Represents the unpacked structure and metadata of an existing PDF Portfolio."""
    title: str
    subtitle: str
    organization: str
    is_evaluation: bool
    files: List[SourceFile]


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
        ".pst": "Outlook PST Archive",
        ".mbox": "MBOX Email Archive",
        ".zip": "ZIP Archive",
    }
    return mapping.get(ext, f"{ext.lstrip('.').upper()} File" if ext else "Binary File")


def normalize_folder_path(folder: str) -> str:
    """Normalizes a relative portfolio folder path to forward slashes without leading/trailing slashes."""
    if not folder:
        return ""
    parts = [p.strip() for p in folder.replace("\\", "/").split("/") if p.strip() and p.strip() != "."]
    return "/".join(parts)


def create_source_file_from_path(
    filepath: Union[str, Path],
    description: str = "",
    folder: str = "",
    bates_number: str = "",
) -> SourceFile:
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
        folder=normalize_folder_path(folder),
        bates_number=bates_number,
    )


def create_source_files_from_directory(
    directory_path: Union[str, Path],
    base_folder_prefix: str = "",
) -> List[SourceFile]:
    """
    Recursively scans a directory and constructs SourceFile items preserving
    nested folder hierarchies inside the PDF Portfolio (/Collection).
    """
    root_dir = Path(directory_path)
    if not root_dir.is_dir():
        return []

    collected: List[SourceFile] = []
    prefix = normalize_folder_path(base_folder_prefix or root_dir.name)
    for file_path in sorted(root_dir.rglob("*")):
        if not file_path.is_file():
            continue
        rel_parent = file_path.parent.relative_to(root_dir).as_posix()
        if rel_parent == ".":
            folder_path = prefix
        else:
            folder_path = normalize_folder_path(f"{prefix}/{rel_parent}" if prefix else rel_parent)
        collected.append(
            create_source_file_from_path(
                file_path,
                folder=folder_path,
            )
        )
    return collected


# ---------------------------------------------------------------------------
# Direct Email Archive (.pst / .mbox / .eml / .msg) E-Discovery Extraction
# ---------------------------------------------------------------------------

def _parse_eml_bytes(
    raw_bytes: bytes,
    default_name: str,
    folder_prefix: str,
    mtime: datetime.datetime,
) -> List[SourceFile]:
    """Parses an RFC 822 / MIME email message and its attachments into SourceFile items."""
    extracted: List[SourceFile] = []
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    subject = str(msg.get("Subject") or default_name).strip()
    sender = str(msg.get("From") or "Unknown Sender").strip()
    date_hdr = str(msg.get("Date") or "").strip()

    msg_date = mtime
    if date_hdr:
        try:
            parsed_dt = email.utils.parsedate_to_datetime(date_hdr)
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=datetime.timezone.utc)
            msg_date = parsed_dt
        except Exception:
            msg_date = mtime

    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", subject)[:60].strip("_") or default_name
    eml_filename = f"{safe_stem}.eml" if not safe_stem.lower().endswith(".eml") else safe_stem
    desc = f"Email from {sender}: {subject}"[:180]

    extracted.append(
        SourceFile(
            filepath=eml_filename,
            filename=eml_filename,
            size=len(raw_bytes),
            file_type="Email Message",
            modified_date=msg_date,
            description=desc,
            data=raw_bytes,
            folder=normalize_folder_path(folder_prefix),
        )
    )

    if msg.is_multipart():
        att_folder = normalize_folder_path(f"{folder_prefix}/Attachments" if folder_prefix else "Attachments")
        for part in msg.walk():
            if part.is_multipart():
                continue
            disp = part.get_content_disposition()
            att_name = part.get_filename()
            if disp == "attachment" or att_name:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                clean_att_name = re.sub(r'[<>:"/\\|?*]', "_", att_name or "attachment.bin")
                suffix = Path(clean_att_name).suffix
                extracted.append(
                    SourceFile(
                        filepath=clean_att_name,
                        filename=clean_att_name,
                        size=len(payload),
                        file_type=infer_file_type(suffix),
                        modified_date=msg_date,
                        description=f"Attachment to '{subject}'",
                        data=payload,
                        folder=att_folder,
                    )
                )

    return extracted


def extract_email_archive(
    archive_path: Union[str, Path],
    base_folder: Optional[str] = None,
) -> List[SourceFile]:
    """
    Extracts messages and attachments from legal e-discovery email archives
    (.pst, .mbox, .eml, .msg) into structured SourceFile items with nested /Collection folders.
    Operates 100% offline using pure Python parsers.
    """
    path = Path(archive_path)
    if not path.is_file():
        raise FileNotFoundError(f"Email archive not found: {path}")

    ext = path.suffix.lower()
    stat = path.stat()
    mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc)
    root_folder = normalize_folder_path(base_folder if base_folder is not None else f"Emails/{path.stem}")

    if ext == ".eml":
        raw = path.read_bytes()
        return _parse_eml_bytes(raw, path.stem, root_folder, mtime)

    if ext == ".mbox":
        results: List[SourceFile] = []
        mbox_obj = mailbox.mbox(str(path), create=False)
        try:
            for idx, message in enumerate(mbox_obj, start=1):
                raw_msg = message.as_bytes()
                results.extend(
                    _parse_eml_bytes(raw_msg, f"Message_{idx:04d}", root_folder, mtime)
                )
        finally:
            mbox_obj.close()
        return results

    if ext in (".pst", ".msg"):
        raw_data = path.read_bytes()
        results = []

        # Scan for embedded RFC 822 / MIME message blocks inside PST (!BDN) or MSG containers
        eml_pattern = re.compile(
            rb"((?:From|Received|Date|Message-ID|Subject|MIME-Version):\s[^\x00]{20,250000}?)(?=\x00|\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        matches = list(eml_pattern.finditer(raw_data))
        seen_hashes = set()
        msg_counter = 0

        for match in matches:
            candidate = match.group(1).strip()
            if b"Subject:" not in candidate and b"From:" not in candidate:
                continue
            digest = hashlib.sha256(candidate).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            msg_counter += 1
            results.extend(
                _parse_eml_bytes(
                    candidate,
                    f"{path.stem}_Message_{msg_counter:04d}",
                    root_folder,
                    mtime,
                )
            )

        # Always preserve the original forensic container (.pst / .msg) if no loose MIME streams matched
        if not results:
            results.append(
                SourceFile(
                    filepath=path,
                    filename=path.name,
                    size=len(raw_data),
                    file_type=infer_file_type(ext),
                    modified_date=mtime,
                    description=f"Forensic {ext.lstrip('.').upper()} Email Container",
                    data=raw_data,
                    folder=root_folder,
                )
            )
        return results

    return [create_source_file_from_path(path, folder=root_folder)]


def _sanitize_pdf_text(text: str) -> str:
    """Escapes parentheses and backslashes for PDF content stream literals."""
    cleaned = (text or "").encode("latin-1", "replace").decode("latin-1")
    return cleaned.replace("\\", "\\\\").replace("(", "[").replace(")", "]")


def _build_collection_folders_tree(
    writer: pypdf.PdfWriter,
    folder_paths: List[str],
) -> Optional[ Tuple[pypdf.generic.IndirectObject, Dict[str, int]] ]:
    """
    Constructs an ISO 32000-1 §12.3.5 /Folders hierarchy for /Collection.
    Returns (root_folder_indirect_ref, mapping_of_folder_path_to_integer_ID).
    """
    unique_folders = sorted({normalize_folder_path(fp) for fp in folder_paths if normalize_folder_path(fp)})
    if not unique_folders:
        return None

    # Expand all intermediate parent directories (e.g., "Exhibits/Financials/2026" -> "Exhibits", "Exhibits/Financials", ...)
    all_nodes = set()
    for fp in unique_folders:
        parts = fp.split("/")
        for i in range(1, len(parts) + 1):
            all_nodes.add("/".join(parts[:i]))

    sorted_paths = sorted(all_nodes, key=lambda p: (p.count("/"), p))
    now_iso = format_iso8824_date(datetime.datetime.now(datetime.timezone.utc))

    # Root folder (ID = 0)
    root_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/CollectionFolder"),
        NameObject("/Name"): TextStringObject("Root"),
        NameObject("/ID"): NumberObject(0),
        NameObject("/CreationDate"): TextStringObject(now_iso),
        NameObject("/ModDate"): TextStringObject(now_iso),
    })
    root_ref = writer._add_object(root_dict)

    path_to_id: Dict[str, int] = {"": 0}
    path_to_dict: Dict[str, DictionaryObject] = {"": root_dict}
    path_to_ref: Dict[str, pypdf.generic.IndirectObject] = {"": root_ref}
    children_by_parent: Dict[str, List[str]] = {"": []}

    next_id = 1
    for path_str in sorted_paths:
        parts = path_str.split("/")
        folder_name = parts[-1]
        parent_path = "/".join(parts[:-1])

        folder_id = next_id
        next_id += 1

        f_dict = DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionFolder"),
            NameObject("/Name"): TextStringObject(folder_name),
            NameObject("/ID"): NumberObject(folder_id),
            NameObject("/CreationDate"): TextStringObject(now_iso),
            NameObject("/ModDate"): TextStringObject(now_iso),
        })
        f_ref = writer._add_object(f_dict)

        path_to_id[path_str] = folder_id
        path_to_dict[path_str] = f_dict
        path_to_ref[path_str] = f_ref
        children_by_parent.setdefault(parent_path, []).append(path_str)
        children_by_parent.setdefault(path_str, [])

    # Wire /Parent, /Child, and /Next pointers across the folder hierarchy
    for parent_path, child_paths in children_by_parent.items():
        if not child_paths:
            continue
        parent_dict = path_to_dict[parent_path]
        parent_ref = path_to_ref[parent_path]

        first_child_path = child_paths[0]
        parent_dict[NameObject("/Child")] = path_to_ref[first_child_path]

        for idx, c_path in enumerate(child_paths):
            c_dict = path_to_dict[c_path]
            c_dict[NameObject("/Parent")] = parent_ref
            if idx + 1 < len(child_paths):
                next_sibling_path = child_paths[idx + 1]
                c_dict[NameObject("/Next")] = path_to_ref[next_sibling_path]

    return root_ref, path_to_id


def build_portfolio(
    output_target: Union[str, Path, BinaryIO],
    files: List[SourceFile],
    title: str = "Document Portfolio",
    subtitle: str = "ISO 32000-1 Interactive Collection",
    organization: str = "Legal & Compliance",
    is_evaluation: bool = True,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    bates_prefix: str = "",
    bates_start: int = 1,
    bates_digits: int = 6,
    include_sha256_manifest: bool = True,
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
        bates_prefix: Optional prefix (e.g., 'EXH-') for automatic sequential Bates numbering.
        bates_start: Starting integer for sequential Bates numbering (default 1).
        bates_digits: Zero-padded width for Bates numbering (default 6 -> EXH-000001).
        include_sha256_manifest: If True, renders a SHA-256 Chain-of-Custody Exhibit Manifest on the Cover Sheet.
    """
    if progress_callback:
        progress_callback(5, "Initializing PDF 1.7 Catalog...")

    writer = pypdf.PdfWriter()

    # 1. Enforce PDF 1.7 Specification (ISO 32000-1 Collections require PDF 1.7)
    writer.pdf_header = "%PDF-1.7"
    writer.root_object[NameObject("/Version")] = NameObject("/1.7")

    # Pre-assign Bates numbers if bates_prefix is configured
    clean_bates_prefix = (bates_prefix or "").strip()
    for idx, item in enumerate(files):
        item.folder = normalize_folder_path(item.folder)
        if clean_bates_prefix and not item.bates_number:
            seq_num = bates_start + idx
            item.bates_number = f"{clean_bates_prefix}{seq_num:0{max(1, bates_digits)}d}"

    # Pre-compute streaming digests (1 MB chunks) so Cover Sheet manifest has SHA-256 hashes
    compressed_cache: List[Tuple[bytes, bytes, str, int]] = []
    total_files = len(files)
    for idx, item in enumerate(files):
        if progress_callback:
            pct = 10 + int(35 * (idx + 1) / max(total_files, 1))
            progress_callback(pct, f"Hashing & streaming ({idx+1}/{total_files}): {item.filename}")
        comp_bytes, md5_digest, sha256_hex, actual_size = item.compress_and_hash_stream()
        item.size = actual_size
        compressed_cache.append((comp_bytes, md5_digest, sha256_hex, actual_size))

    # 2. Render Fallback Cover Sheet (Page 1) with SHA-256 Exhibit Manifest
    if progress_callback:
        progress_callback(50, "Rendering Fallback Cover Sheet & SHA-256 Exhibit Manifest...")

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
    font_mono = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Courier"),
    })

    font_resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): writer._add_object(font_bold),
            NameObject("/F2"): writer._add_object(font_reg),
            NameObject("/F3"): writer._add_object(font_oblique),
            NameObject("/F4"): writer._add_object(font_mono),
        })
    })
    cover_page[NameObject("/Resources")] = font_resources

    # Persist Cover Sheet metadata in PDF Info dictionary for round-trip portfolio editing
    writer.add_metadata({
        "/Title": title,
        "/Subject": subtitle,
        "/Author": organization,
        "/Creator": "PDF Portfolio Maker (ISO 32000-1)",
    })

    clean_title = _sanitize_pdf_text(title)
    clean_subtitle = _sanitize_pdf_text(subtitle)
    clean_org = _sanitize_pdf_text(organization)
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
        f"(Organization: {clean_org} | Date Generated: {date_str} | Total Source Files: {total_files}) Tj",
        "ET",
    ]

    # Evaluation Watermark Banner
    if is_evaluation:
        stream_ops.extend([
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
        "50 475 512 135 re",
        "f",
        "0.82 0.85 0.90 RG",
        "1 w",
        "50 475 512 135 re",
        "S",
        "BT",
        "0.15 0.15 0.15 rg",
        "/F1 11 Tf",
        "65 585 Td",
        "(Interactive PDF Portfolio Notice) Tj",
        "/F2 9.5 Tf",
        "0 -18 Td",
        "(This document is an interactive ISO 32000-1 standardized PDF Portfolio containing attached) Tj",
        "0 -14 Td",
        "(source files preserved in their original formats with complete metadata and signatures.) Tj",
        "0 -18 Td",
        "(To browse, open, or extract files, view this document in Adobe Acrobat Reader or another) Tj",
        "0 -14 Td",
        "(compliant PDF Portfolio reader.) Tj",
        "0 -18 Td",
        "(In web browser and mobile readers, you can access files via the Attachments / Paperclip tab.) Tj",
        "ET",
    ])

    # Render Automated SHA-256 Chain-of-Custody Exhibit Manifest Table on Cover Sheet
    if include_sha256_manifest and files:
        stream_ops.extend([
            "0.12 0.16 0.23 rg",
            "50 435 512 22 re",
            "f",
            "BT",
            "/F1 9 Tf",
            "1 1 1 rg",
            "58 443 Td",
            "(CHAIN-OF-CUSTODY SHA-256 EXHIBIT MANIFEST) Tj",
            "ET",
            "0.91 0.93 0.96 rg",
            "50 417 512 18 re",
            "f",
            "BT",
            "/F1 8 Tf",
            "0.15 0.20 0.28 rg",
            "58 423 Td",
            "(BATES / ID        SOURCE FILE / FOLDER                        SIZE        SHA-256 DIGEST [PREFIX..SUFFIX]) Tj",
            "ET",
        ])

        y_cursor = 402
        max_rows_on_cover = min(len(files), 22)
        for idx in range(max_rows_on_cover):
            item = files[idx]
            _, _, sha_hex, actual_size = compressed_cache[idx]
            bates_label = item.bates_number if item.bates_number else f"ITEM-{idx+1:03d}"
            display_path = f"{item.folder}/{item.filename}" if item.folder else item.filename
            if len(display_path) > 34:
                display_path = display_path[:31] + "..."
            size_kb = f"{actual_size / 1024.0:.1f} KB" if actual_size >= 1024 else f"{actual_size} B"
            short_sha = f"{sha_hex[:12]}...{sha_hex[-8:]}"
            row_line = f"{bates_label:<14} {display_path:<35} {size_kb:>10}   {short_sha}"
            clean_row = _sanitize_pdf_text(row_line)

            if idx % 2 == 1:
                stream_ops.extend([
                    "0.97 0.98 0.99 rg",
                    f"50 {y_cursor - 4} 512 15 re",
                    "f",
                ])

            stream_ops.extend([
                "BT",
                "/F4 7.5 Tf",
                "0.15 0.15 0.15 rg",
                f"58 {y_cursor} Td",
                f"({clean_row}) Tj",
                "ET",
            ])
            y_cursor -= 16

        if len(files) > max_rows_on_cover:
            rem = len(files) - max_rows_on_cover
            stream_ops.extend([
                "BT",
                "/F3 8 Tf",
                "0.35 0.40 0.48 rg",
                f"58 {y_cursor} Td",
                f"(+ {rem} additional Source File(s) embedded in /Collection catalog with full SHA-256 metadata.) Tj",
                "ET",
            ])

    cs = DecodedStreamObject()
    cs.set_data("\n".join(stream_ops).encode("latin-1", "replace"))
    cover_page[NameObject("/Contents")] = writer._add_object(cs)

    # 3. Define Collection Schema (/CollectionSchema - ISO 32000-1 Table 156)
    if progress_callback:
        progress_callback(60, "Defining Collection Schema & Hierarchy...")

    schema = DictionaryObject({
        NameObject("/Type"): NameObject("/CollectionSchema"),
        NameObject("/BatesNumber"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/S"),
            NameObject("/N"): TextStringObject("Bates / Exhibit ID"),
            NameObject("/O"): NumberObject(0),
            NameObject("/V"): BooleanObject(bool(clean_bates_prefix or any(f.bates_number for f in files))),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/FileName"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/F"),
            NameObject("/N"): TextStringObject("File Name"),
            NameObject("/O"): NumberObject(1),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/Folder"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/S"),
            NameObject("/N"): TextStringObject("Folder"),
            NameObject("/O"): NumberObject(2),
            NameObject("/V"): BooleanObject(any(bool(f.folder) for f in files)),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/FileSize"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/Size"),
            NameObject("/N"): TextStringObject("Size"),
            NameObject("/O"): NumberObject(3),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/DocType"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/S"),
            NameObject("/N"): TextStringObject("Type"),
            NameObject("/O"): NumberObject(4),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/ModDate"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/ModDate"),
            NameObject("/N"): TextStringObject("Date Modified"),
            NameObject("/O"): NumberObject(5),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/Description"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/Desc"),
            NameObject("/N"): TextStringObject("Description"),
            NameObject("/O"): NumberObject(6),
            NameObject("/V"): BooleanObject(True),
            NameObject("/E"): BooleanObject(False),
        }),
        NameObject("/SHA256"): DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionField"),
            NameObject("/Subtype"): NameObject("/S"),
            NameObject("/N"): TextStringObject("SHA-256 Checksum"),
            NameObject("/O"): NumberObject(7),
            NameObject("/V"): BooleanObject(include_sha256_manifest),
            NameObject("/E"): BooleanObject(False),
        }),
    })

    # 4. Construct Collection Dictionary (/Collection - ISO 32000-1 Table 155)
    collection_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/Collection"),
        NameObject("/View"): NameObject("/D"),  # 'D' = Details grid view
        NameObject("/Schema"): schema,
        NameObject("/Sort"): DictionaryObject({
            NameObject("/S"): NameObject("/BatesNumber" if clean_bates_prefix else "/FileName"),
            NameObject("/A"): BooleanObject(True),
        }),
    })

    folder_tree_result = _build_collection_folders_tree(writer, [f.folder for f in files])
    folder_id_map: Dict[str, int] = {"": 0}
    if folder_tree_result is not None:
        root_folder_ref, folder_id_map = folder_tree_result
        collection_dict[NameObject("/Folders")] = root_folder_ref

    writer.root_object[NameObject("/Collection")] = writer._add_object(collection_dict)
    writer.root_object[NameObject("/PageMode")] = NameObject("/UseAttachments")

    # 5. Embed Source Files with Chunk-Compressed Streams & Collection Items (/CI - Table 48)
    for idx, item in enumerate(files):
        if progress_callback:
            pct = 65 + int(25 * (idx + 1) / max(total_files, 1))
            progress_callback(pct, f"Embedding ({idx+1}/{total_files}): {item.filename}")

        comp_bytes, md5_digest, sha256_hex, actual_size = compressed_cache[idx]
        mime = mimetypes.guess_type(item.filename)[0] or "application/octet-stream"

        # Register attachment placeholder and replace stream payload with pre-compressed Flate stream
        att = writer.add_attachment(item.filename, b"")
        filespec = att.pdf_object

        ef_dict = filespec[NameObject("/EF")]

        flate_stream = EncodedStreamObject()
        flate_stream._data = comp_bytes
        flate_stream[NameObject("/Type")] = NameObject("/EmbeddedFile")
        flate_stream[NameObject("/Subtype")] = NameObject(f"/{mime}")
        flate_stream[NameObject("/Filter")] = NameObject("/FlateDecode")
        flate_stream[NameObject("/Params")] = DictionaryObject({
            NameObject("/Size"): NumberObject(actual_size),
            NameObject("/CheckSum"): ByteStringObject(md5_digest),
            NameObject("/ModDate"): TextStringObject(format_iso8824_date(item.modified_date)),
        })
        flate_ref = writer._add_object(flate_stream)
        ef_dict[NameObject("/F")] = flate_ref
        ef_dict[NameObject("/UF")] = flate_ref

        # Enhance File Specification Dictionary
        qualified_name = f"<{folder_id_map.get(item.folder, 0)}>{item.filename}" if item.folder in folder_id_map and item.folder else item.filename
        filespec[NameObject("/UF")] = TextStringObject(item.filename)
        filespec[NameObject("/F")] = TextStringObject(item.filename)
        if item.folder:
            filespec[NameObject("/CollectionFolderPath")] = TextStringObject(item.folder)
            filespec[NameObject("/CollectionQualifiedName")] = TextStringObject(qualified_name)
        filespec[NameObject("/Desc")] = TextStringObject(item.description)

        # Link Collection Item Dictionary
        ci_dict = DictionaryObject({
            NameObject("/Type"): NameObject("/CollectionItem"),
            NameObject("/BatesNumber"): TextStringObject(item.bates_number),
            NameObject("/FileName"): TextStringObject(item.filename),
            NameObject("/Folder"): TextStringObject(item.folder),
            NameObject("/FileSize"): NumberObject(actual_size),
            NameObject("/DocType"): TextStringObject(item.file_type),
            NameObject("/ModDate"): TextStringObject(format_iso8824_date(item.modified_date)),
            NameObject("/Description"): TextStringObject(item.description),
            NameObject("/SHA256"): TextStringObject(sha256_hex),
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


# ---------------------------------------------------------------------------
# Round-Trip Portfolio Reader, Unpacker, and Appender
# ---------------------------------------------------------------------------

def _parse_iso8824_date(pdf_date_str: str) -> datetime.datetime:
    """Parses a PDF ISO 8824 date string (D:YYYYMMDDHHmmSS...) into a UTC datetime."""
    cleaned = re.sub(r"^D:", "", (pdf_date_str or "").strip())
    digits = re.match(r"^(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", cleaned)
    if not digits:
        return datetime.datetime.now(datetime.timezone.utc)
    year = int(digits.group(1))
    month = int(digits.group(2) or 1)
    day = int(digits.group(3) or 1)
    hour = int(digits.group(4) or 0)
    minute = int(digits.group(5) or 0)
    second = int(digits.group(6) or 0)
    try:
        return datetime.datetime(year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc)
    except ValueError:
        return datetime.datetime.now(datetime.timezone.utc)


def inspect_portfolio(portfolio_source: Union[str, Path, BinaryIO]) -> PortfolioManifest:
    """
    Opens an existing ISO 32000-1 PDF Portfolio (or PDF with /EmbeddedFiles)
    and reconstructs its Cover Sheet metadata and ordered list of SourceFile items.
    """
    reader = pypdf.PdfReader(portfolio_source)
    meta = reader.metadata or {}
    title = str(meta.get("/Title") or "Document Portfolio")
    subtitle = str(meta.get("/Subject") or "ISO 32000-1 Interactive Collection")
    organization = str(meta.get("/Author") or "Legal & Compliance")

    is_eval = False
    if len(reader.pages) > 0:
        try:
            page0_contents = reader.pages[0].get_contents()
            if page0_contents and b"DEMO / EVALUATION COPY" in page0_contents.get_data():
                is_eval = True
        except Exception:
            is_eval = False

    extracted_files: List[SourceFile] = []
    root = reader.trailer.get("/Root", {})
    if hasattr(root, "get_object"):
        root = root.get_object()

    names_dict = root.get("/Names")
    if names_dict is not None:
        names_dict = names_dict.get_object()
        ef_tree = names_dict.get("/EmbeddedFiles")
        if ef_tree is not None:
            ef_tree = ef_tree.get_object()
            names_array = ef_tree.get("/Names", [])
            for i in range(1, len(names_array), 2):
                filespec = names_array[i].get_object()
                filename = str(filespec.get("/UF") or filespec.get("/F") or f"embedded_{i}")
                description = str(filespec.get("/Desc") or "")
                folder = str(filespec.get("/CollectionFolderPath") or "")
                bates_num = ""
                sha_hex = ""
                file_type_label = infer_file_type(Path(filename).suffix)
                mod_dt = datetime.datetime.now(datetime.timezone.utc)

                ci_ref = filespec.get("/CI")
                if ci_ref is not None:
                    ci = ci_ref.get_object()
                    filename = str(ci.get("/FileName") or filename)
                    description = str(ci.get("/Description") or description)
                    folder = str(ci.get("/Folder") or folder)
                    bates_num = str(ci.get("/BatesNumber") or "")
                    sha_hex = str(ci.get("/SHA256") or "")
                    file_type_label = str(ci.get("/DocType") or file_type_label)
                    if "/ModDate" in ci:
                        mod_dt = _parse_iso8824_date(str(ci["/ModDate"]))

                ef_dict = filespec.get("/EF")
                raw_bytes = b""
                if ef_dict is not None:
                    ef_dict = ef_dict.get_object()
                    stream_ref = ef_dict.get("/F") or ef_dict.get("/UF")
                    if stream_ref is not None:
                        stream_obj = stream_ref.get_object()
                        raw_bytes = stream_obj.get_data()

                if not sha_hex and raw_bytes:
                    sha_hex = hashlib.sha256(raw_bytes).hexdigest()

                extracted_files.append(
                    SourceFile(
                        filepath=filename,
                        filename=filename,
                        size=len(raw_bytes),
                        file_type=file_type_label,
                        modified_date=mod_dt,
                        description=description,
                        data=raw_bytes,
                        folder=normalize_folder_path(folder),
                        bates_number=bates_num,
                        sha256=sha_hex,
                    )
                )

    return PortfolioManifest(
        title=title,
        subtitle=subtitle,
        organization=organization,
        is_evaluation=is_eval,
        files=extracted_files,
    )


def extract_portfolio(
    portfolio_source: Union[str, Path, BinaryIO],
    output_dir: Union[str, Path],
) -> List[Path]:
    """
    Unpacks all embedded Source Files from an existing PDF Portfolio into `output_dir`,
    preserving nested `/Collection` folder hierarchies and modification timestamps.
    """
    manifest = inspect_portfolio(portfolio_source)
    target_root = Path(output_dir)
    target_root.mkdir(parents=True, exist_ok=True)

    written_paths: List[Path] = []
    for item in manifest.files:
        rel_folder = normalize_folder_path(item.folder)
        dest_dir = (target_root / rel_folder) if rel_folder else target_root
        dest_dir.mkdir(parents=True, exist_ok=True)

        safe_name = Path(item.filename).name
        dest_file = dest_dir / safe_name
        # Avoid overwriting if duplicate filenames exist in the same folder
        counter = 1
        while dest_file.exists():
            dest_file = dest_dir / f"{Path(safe_name).stem}_{counter}{Path(safe_name).suffix}"
            counter += 1

        dest_file.write_bytes(item.read_bytes())
        try:
            ts = item.modified_date.timestamp()
            os.utime(dest_file, (ts, ts))
        except OSError:
            pass
        written_paths.append(dest_file)

    return written_paths


def append_to_portfolio(
    existing_portfolio: Union[str, Path, BinaryIO],
    output_target: Union[str, Path, BinaryIO],
    additional_files: List[SourceFile],
    is_evaluation: Optional[bool] = None,
    bates_prefix: str = "",
    bates_start: int = 1,
    bates_digits: int = 6,
    include_sha256_manifest: bool = True,
) -> PortfolioManifest:
    """
    Loads an existing ISO 32000-1 PDF Portfolio, appends `additional_files`
    (preserving existing Source Files and metadata), and writes the updated PDF Portfolio.
    """
    manifest = inspect_portfolio(existing_portfolio)
    merged_files = list(manifest.files) + list(additional_files)
    eval_flag = manifest.is_evaluation if is_evaluation is None else is_evaluation

    build_portfolio(
        output_target=output_target,
        files=merged_files,
        title=manifest.title,
        subtitle=manifest.subtitle,
        organization=manifest.organization,
        is_evaluation=eval_flag,
        bates_prefix=bates_prefix,
        bates_start=bates_start,
        bates_digits=bates_digits,
        include_sha256_manifest=include_sha256_manifest,
    )
    manifest.files = merged_files
    manifest.is_evaluation = eval_flag
    return manifest
