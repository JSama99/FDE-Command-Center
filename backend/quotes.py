"""Exact quotation verification against original source text.

Every quotation must match its source document byte-for-byte (case, punctuation,
whitespace). Document identifiers and character offsets are preserved on the
verified result. Anything invented or altered raises QuoteVerificationError.
Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class QuoteVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    path: str
    text: str


@dataclass(frozen=True)
class VerifiedQuote:
    doc_id: str
    quote: str
    start: int
    end: int

    def excerpt(self, documents: dict[str, SourceDocument]) -> str:
        return documents[self.doc_id].text[self.start : self.end]


CASE_DOCUMENTS = (
    ("policy", "fixtures/case-001/policy.md"),
    ("dispatcher", "fixtures/case-001/dispatcher.md"),
    ("manager", "fixtures/case-001/manager.md"),
)


def load_case_documents(base_dir: str | Path = ".") -> dict[str, SourceDocument]:
    base = Path(base_dir)
    docs: dict[str, SourceDocument] = {}
    for doc_id, rel in CASE_DOCUMENTS:
        text = (base / rel).read_text(encoding="utf-8")
        docs[doc_id] = SourceDocument(doc_id=doc_id, path=rel, text=text)
    return docs


def verify_quote(documents: dict[str, SourceDocument], doc_id: str, quote: str) -> VerifiedQuote:
    if not quote:
        raise QuoteVerificationError("empty quotation is not verifiable")
    doc = documents.get(doc_id)
    if doc is None:
        raise QuoteVerificationError(f"unknown document: {doc_id}")
    start = doc.text.find(quote)
    if start < 0:
        raise QuoteVerificationError(f"quotation not found verbatim in {doc_id}")
    return VerifiedQuote(doc_id=doc_id, quote=quote, start=start, end=start + len(quote))
