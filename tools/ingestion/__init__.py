"""Artifact parsers.

Both parsers are read-only with respect to their source files: the platform never
writes back to a workbook or a package it was given.
"""
from .package import PackageIngestResult, ingest_package
from .workbook import WorkbookIngestResult, ingest_workbook

__all__ = [
    "ingest_package", "PackageIngestResult",
    "ingest_workbook", "WorkbookIngestResult",
]
