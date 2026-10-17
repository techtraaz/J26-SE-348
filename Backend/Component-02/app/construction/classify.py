import re

from app.construction.documents import LoadedDocument

# standard, amendment and legislation are ingested into the KG.
# client_document goes to the evidence ledger instead; unknown is left for a person.
_ACT = re.compile(r"\bact,?\s+no\.?\s*\d+\s+of\s+\d{4}")
_CLIENT_WORDS = ("invoice", "receipt", "bank statement", "purchase order", "payment voucher",
                 "goods received note", "trial balance")


def classify_document(doc: LoadedDocument) -> str:
    head = " ".join(p.text for p in doc.pages[:3]).lower()
    if doc.code:
        title = " ".join(head[:200].split())
        return "amendment" if "amendments to" in title else "standard"
    if _ACT.search(head):
        return "legislation"
    if any(word in head for word in _CLIENT_WORDS):
        return "client_document"
    return "unknown"
