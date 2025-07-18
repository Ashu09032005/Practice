import os
import json
import time
import fitz  # PyMuPDF
import re
from collections import Counter

def clean_text(text):
    return re.sub(r'\s+', ' ', text.strip())

def is_bold(span):
    font = span.get("font", "").lower()
    flags = span.get("flags", 0)
    return "bold" in font or (flags & 2)

def detect_heading_level_by_number(text):
    if re.match(r'^\d+\.\s', text) and len(text.split()) <= 6:
        return "H1"
    elif re.match(r'^\d+\.\d+\s', text) and len(text.split()) <= 8:
        return "H2"
    elif re.match(r'^\d+\.\d+\.\d+\s', text) and len(text.split()) <= 10:
        return "H3"
    return None

def is_questionnaire_item(text, font_size):
    return (
        re.match(r'^\d{1,2}\.', text.strip()) and
        font_size <= 10.5 and
        len(text.split()) >= 3 and
        not text.strip().endswith(":")
    )

def is_likely_heading(text, font_size, avg_font_size):
    text = clean_text(text)

    if len(text) < 2 or len(text) > 200:
        return False

    if re.match(r'^[\d\s\.\-/]+$', text):
        return False

    skip_patterns = [
        r'^\d{1,3}$',
        r'^page \d+',
        r'^\d{4}$',
        r'^©.*copyright.*$',
        r'^version.*\d+.*$',
    ]

    for pattern in skip_patterns:
        if re.match(pattern, text.lower()):
            return False

    heading_indicators = [
        text.isupper(),
        text.istitle(),
        text.endswith(':'),
        len(text.split()) <= 10,
    ]

    return font_size >= avg_font_size * 1.05 or any(heading_indicators)

def analyze_font_sizes(doc):
    font_sizes = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line.get("spans", []):
                    if span["text"].strip():
                        font_sizes.append(round(span["size"], 1))

    if not font_sizes:
        return {}

    font_counter = Counter(font_sizes)
    sorted_fonts = sorted(font_counter.items(), key=lambda x: (-x[1], -x[0]))
    body_font = sorted_fonts[0][0]
    unique_sizes = sorted(set(font_sizes), reverse=True)

    if len(unique_sizes) >= 4:
        thresholds = {
            "body": body_font,
            "H3": unique_sizes[min(2, len(unique_sizes)-1)],
            "H2": unique_sizes[min(1, len(unique_sizes)-1)],
            "H1": unique_sizes[0],
        }
    else:
        thresholds = {
            "body": body_font,
            "H3": body_font * 1.15,
            "H2": body_font * 1.25,
            "H1": body_font * 1.35,
        }

    return thresholds

def classify_heading_level(text, font_size, thresholds):
    level_by_number = detect_heading_level_by_number(text)
    if level_by_number:
        return level_by_number

    if font_size >= thresholds.get("H1", 16):
        return "H1"
    elif font_size >= thresholds.get("H2", 14):
        return "H2"
    elif font_size >= thresholds.get("H3", 12):
        return "H3"
    return None

def extract_title_from_document(doc):
    title_candidates = []
    for page_num in range(min(3, len(doc))):
        page = doc[page_num]
        for block in page.get_text("dict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                if not line.get("spans"):
                    continue
                line_text = ""
                font_sizes = []
                for span in line["spans"]:
                    if span["text"].strip():
                        line_text += span["text"]
                        font_sizes.append(span["size"])
                line_text = clean_text(line_text)
                if not line_text or not font_sizes:
                    continue
                avg_size = sum(font_sizes) / len(font_sizes)
                if 10 < len(line_text) < 150 and avg_size > 10 and not line_text.lower().startswith('page'):
                    title_candidates.append({
                        'text': line_text,
                        'size': avg_size,
                        'page': page_num + 1,
                        'length': len(line_text)
                    })
    if not title_candidates:
        return "Untitled"
    title_candidates.sort(key=lambda x: (-x['size'], x['page']))
    return title_candidates[0]['text']

def is_table_like(text, line=None):
    if not line:
        return False

    spans = line.get("spans", [])
    x_positions = [round(span["bbox"][0]) for span in spans if span["text"].strip()]

    if len(x_positions) < 2:
        return False

    col_positions = Counter(x_positions)
    repeated_cols = [pos for pos, count in col_positions.items() if count >= 2]

    return len(repeated_cols) >= 2 or len(spans) >= 4

def extract_headings_from_document(doc, title, thresholds):
    headings = []
    seen_headings = set()
    avg_font_size = thresholds.get("body", 12)

    for page_num, page in enumerate(doc, 1):
        for block in page.get_text("dict")["blocks"]:
            if "lines" not in block:
                continue

            block_lines = block.get("lines", [])

            for line in block_lines:
                if not line.get("spans"):
                    continue
                line_text = ""
                font_sizes = []
                is_bold_line = False
                for span in line["spans"]:
                    if span["text"].strip():
                        line_text += span["text"]
                        font_sizes.append(span["size"])
                        if is_bold(span):
                            is_bold_line = True
                line_text = clean_text(line_text)
                if not line_text or not font_sizes:
                    continue
                avg_font_size_line = sum(font_sizes) / len(font_sizes)

                if is_table_like(line_text, line):
                    continue

                # skip form-style numeric prefix + long text (e.g. 12. Amount of advance required.)
                if re.match(r'^\d{1,2}\.', line_text.strip()) and len(line_text.split()) >= 5:
                    continue

                if not (is_likely_heading(line_text, avg_font_size_line, avg_font_size) or is_bold_line):
                    continue

                if clean_text(title).lower() == line_text.lower():
                    continue

                heading_key = line_text.lower().strip()
                if heading_key in seen_headings:
                    continue

                level = classify_heading_level(line_text, avg_font_size_line, thresholds)
                if level:
                    headings.append({
                        "level": level,
                        "text": line_text + " ",
                        "page": page_num-1
                    })
                    seen_headings.add(heading_key)
    return headings

def extract_outline_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return {"title": "Empty Document", "outline": []}
        title = extract_title_from_document(doc)
        thresholds = analyze_font_sizes(doc)
        outline = extract_headings_from_document(doc, title, thresholds)
        doc.close()
        return {
            "title": title,
            "outline": outline
        }
    except Exception as e:
        print(f"Error processing {pdf_path}: {str(e)}")
        return {"title": "Error", "outline": []}

def run_extraction():
    input_folder = "input"
    output_folder = "output"
    os.makedirs(input_folder, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)

    pdf_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"No PDF files found in '{input_folder}' folder!")
        return

    start_time = time.time()
    print(f"Starting processing of {len(pdf_files)} PDF files...")

    for filename in pdf_files:
        print(f"Processing: {filename}")
        input_path = os.path.join(input_folder, filename)
        result = extract_outline_from_pdf(input_path)

        output_filename = os.path.splitext(filename)[0] + ".json"
        output_path = os.path.join(output_folder, output_filename)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4, ensure_ascii=False)

        print(f"  -> Saved: {output_filename}")
        print(f"  -> Title: {result['title']}")
        print(f"  -> Headings found: {len(result['outline'])}")
        print()

    elapsed_time = time.time() - start_time
    print(f"Processing completed in {elapsed_time:.2f} seconds.")

if __name__ == "__main__":
    run_extraction()
