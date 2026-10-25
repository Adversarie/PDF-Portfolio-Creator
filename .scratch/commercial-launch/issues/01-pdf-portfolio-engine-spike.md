# 01 PDF Portfolio Engine Spike

Type: research
Status: resolved
Blocked by:

## Question

Can `pypdf` construct compliant ISO 32000-1 `/Collection` dictionaries with `/EmbeddedFiles` and a `/CF` schema, or does the project require `pikepdf` (QPDF wrapper) or `pymupdf`?

Investigate against primary PDF 1.7 / ISO 32000-1 specifications and Python PDF library documentation and source code:
1. What exact dictionary structure (`/Root -> /Collection`, `/CollectionSchema`, `/EmbeddedFiles` name tree) is required for Adobe Acrobat and other compliant viewers to display the interactive Portfolio interface?
2. Can this be constructed using `pypdf`'s low-level dictionary manipulation (`pypdf.generic.DictionaryObject`), or does `pikepdf` provide cleaner, safer primitive support?
3. Produce a standalone runnable Python script demonstrating the creation of a valid PDF Portfolio containing at least two embedded files (e.g., a PDF and an Excel spreadsheet) with metadata columns (Name, Size, Type, Date, Description) and a fallback Cover Sheet.

## Answer

### 1. Selected Library: `pypdf` (>= 5.1.0)
- **Verdict**: `pypdf` can construct 100% compliant ISO 32000-1 (PDF 1.7) PDF Portfolios using its low-level dictionary primitives (`DictionaryObject`, `ArrayObject`, `NameObject`, `TextStringObject`) and `writer.add_attachment()`.
- **Senior Dev Rationale**: Avoids adding C++ dependencies (`pikepdf` requires QPDF binaries; `pymupdf` requires MuPDF and carries a commercial-prohibitive AGPLv3 license). Pure Python guarantees zero DLL packaging headaches on Windows with PyInstaller.

### 2. ISO 32000-1 Object Architecture
- **Catalog Root (`/Root`)**:
  - `/Version /1.7` (enforces PDF 1.7 specification).
  - `/PageMode /UseAttachments` (ensures non-portfolio viewers open the attachment panel).
  - `/Collection`: Points to `/Collection` dictionary with `/View /D` (Details spreadsheet view) and `/Sort` (`/FileName` ascending).
- **Schema (`/CollectionSchema`)**:
  - Defines 5 standardized columns: `/FileName` (subtype `/F`), `/FileSize` (subtype `/Size`), `/DocType` (subtype `/S`), `/ModDate` (subtype `/ModDate`), and `/Description` (subtype `/Desc`).
- **File Specifications & Collection Items (`/CI`)**:
  - Attached via `writer.add_attachment(filename, data)`.
  - Stream subtype set to MIME type (e.g. `/application#2Fpdf`).
  - `/Filespec` dictionary augmented with `/UF` (Unicode filename) and a `/CI` (`/CollectionItem`) dictionary holding the individual file's column metadata.
- **Fallback Cover Sheet**:
  - Rendered on Page 1 with vector banner and instructions for non-portfolio viewers (browser PDF viewers, Apple Preview, mobile).

