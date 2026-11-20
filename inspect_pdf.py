import pdfplumber

PATH = "data/nmra_mrp.pdf"

with pdfplumber.open(PATH) as pdf:
    print("total pages:", len(pdf.pages))
    page = pdf.pages[0]
    tables = page.extract_tables()
    print("tables found on page 1:", len(tables))
    if tables:
        for row in tables[0][:6]:
            print(row)
    else:
        print("--- no table detected, raw text ---")
        print((page.extract_text() or "")[:1200])
