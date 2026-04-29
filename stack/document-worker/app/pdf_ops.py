from io import BytesIO
from pypdf import PdfReader, PdfWriter

def pdf_remove_pages(pdf_bytes: bytes, remove_pages_1based: list[int]) -> bytes:
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    remove = set(p-1 for p in remove_pages_1based if p > 0)
    for i, page in enumerate(reader.pages):
        if i not in remove:
            writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()
