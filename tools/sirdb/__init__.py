"""SIR/SIRG reference database — the foundation for generating the M2C ``Import`` sheet.

Modules:
    workbook   read every cell of the M2C workbook (cached value + formula text), losslessly
    profile    Phase 1: inventory, field analysis and reconciliation findings (read-only)
    migrate    Phase 2: apply the versioned PostgreSQL migrations in ``migrations/sirdb``
    loader     Phase 3: idempotent load of a workbook into PostgreSQL
    resolve    Phase 4: reference resolution, rule validation and the final Import dataset

Nothing here evaluates the workbook's ``Other Logic`` text: it is stored and compared as text.
"""
