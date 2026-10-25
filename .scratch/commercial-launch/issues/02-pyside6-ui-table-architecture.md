# 02 PySide6 UI Table Architecture

Type: prototype
Status: resolved
Blocked by: 01

## Question

How should the desktop UI be structured in PySide6 (Qt) to handle source file ingestion, metadata editing, cover sheet configuration, and background execution?

1. Implement a prototype PySide6 desktop window containing:
   - A `QTableWidget` / `QTableView` displaying source files with columns: Name, Size, Type, Date Modified, and an editable Description.
   - Drag-and-drop support for dropping files directly into the window from Explorer.
   - Action controls: Add Files, Remove Selected, Move Up, Move Down, Clear All.
   - Cover Sheet settings panel: Portfolio Title, Subtitle, Author/Organization, and Date.
   - Asynchronous worker (`QThread`) with progress bar to prevent GUI freezing during portfolio generation.
2. Verify native Windows styling, high-DPI scaling, and clean separation between UI actions and the PDF engine interface.

## Answer

Prototype implemented and verified in [prototype_app.py](../../prototype_app.py).

### Architecture Highlights:
1. **Source File Table Model (`QTableWidget`)**:
   - 5 structured columns: File Name, Size (formatted KB/MB), Inferred Document Type, Date Modified, and an inline-editable Description cell.
   - Selection model supports extended multi-row selection and keyboard navigation.
2. **Windows Explorer Drag-and-Drop**:
   - Accepts dropped files directly via `dragEnterEvent` and `dropEvent` (filtering `mimeData().urls()`), automatically inspecting metadata and ignoring duplicates.
3. **Cover Sheet Configuration**:
   - Live settings panel for Title, Subtitle, and Organization / Author, generating professional vector graphics and compatibility notices on Page 1.
4. **Non-Blocking Execution (`PortfolioBuilderWorker` on `QThread`)**:
   - Background worker delegates portfolio assembly off the GUI thread with granular progress updates (10% to 100%), keeping the UI responsive even on gigabyte-sized files.
   - Verified headless run: correctly builds ISO 32000-1 `/Collection` dictionary and attachments without errors.

