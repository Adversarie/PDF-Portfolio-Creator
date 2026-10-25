# PDF Portfolio Maker

A privacy-focused desktop application for creating standardized, interactive PDF Portfolios (ISO 32000-1) for compliance-bound professionals.

## Language

**PDF Portfolio**:
A standardized PDF document containing a `/Collection` dictionary (ISO 32000-1 / PDF 1.7) that acts as an envelope packaging multiple distinct files in their original formats with individual metadata and signatures preserved.
_Avoid_: Merged PDF, Combined PDF, PDF Package, Binder

**Source File**:
An individual document or asset (PDF, DOCX, XLSX, image, etc.) embedded inside a PDF Portfolio as an embedded file stream.
_Avoid_: Attachment, Page, Segment

**Cover Sheet**:
The visual parent PDF page displayed when a PDF reader opens the file or when a reader does not support interactive `/Collection` rendering.
_Avoid_: Splash screen, Home page, Title page

**Collection Schema**:
The standardized set of field definitions (Name, Size, Type, Date, Description) stored in the `/CF` dictionary that dictates the metadata columns displayed in the Portfolio viewer.
_Avoid_: Custom attributes, properties table, column layout

**License Key**:
A cryptographically signed string verified completely offline by the desktop application using a bundled public key to validate product purchase without outbound network requests.
_Avoid_: Serial number, activation code, registration token

