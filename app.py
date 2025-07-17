import os
import json
import time
import fitz  # PyMuPDF for PDF parsing

# Decide the heading level based on font size
def classify_heading(size, font_thresholds):
    if size >= font_thresholds['H1']:
        return "H1"
    elif size >= font_thresholds['H2']:
        return "H2"
    elif size >= font_thresholds['H3']:
        return "H3"
    return None  # Not a heading

# Reads and processes a single PDF file
def extract_outline_from_pdf(pdf_path):
    document = fitz.open(pdf_path)
    outline_data = []

    file_name = os.path.basename(pdf_path)
    title = os.path.splitext(file_name)[0].replace("_", " ").title()

    # Dictionary to track font sizes and how often they appear
    font_counter = {}

    # First sweep: collect font size frequencies
    for page in document:
        page_data = page.get_text("dict")
        for block in page_data.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    rounded_size = round(span["size"], 1)
                    if rounded_size not in font_counter:
                        font_counter[rounded_size] = 1
                    else:
                        font_counter[rounded_size] += 1

    # Abort if no text was found
    if not font_counter:
        return {"title": title, "outline": []}

    # Determine thresholds for H1, H2, H3 based on largest font size
    largest_font = max(font_counter)
    thresholds = {
        "H1": largest_font,
        "H2": largest_font * 0.95,
        "H3": largest_font * 0.9
    }

    # Second sweep: extract headings based on average font size
    for page_index, page in enumerate(document, start=1):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            for line in block.get("lines", []):
                collected_text = ""
                sizes = []

                for span in line.get("spans", []):
                    text_piece = span["text"].strip()
                    if text_piece:
                        collected_text += text_piece + " "
                        sizes.append(span["size"])

                if not collected_text.strip() or not sizes:
                    continue

                average_size = sum(sizes) / len(sizes)
                heading_type = classify_heading(average_size, thresholds)

                if heading_type:
                    outline_data.append({
                        "level": heading_type,
                        "text": collected_text.strip(),
                        "page": page_index
                    })

    return {
        "title": title,
        "outline": outline_data
    }

# Entry point: reads files and writes output JSONs
def run_extraction():
    input_folder = "input"
    output_folder = "output"

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    print("Started processing...")
    start = time.time()

    for file in os.listdir(input_folder):
        if file.endswith(".pdf"):
            input_path = os.path.join(input_folder, file)
            result = extract_outline_from_pdf(input_path)

            json_output = os.path.splitext(file)[0] + ".json"
            output_path = os.path.join(output_folder, json_output)

            with open(output_path, "w", encoding="utf-8") as json_file:
                json.dump(result, json_file, indent=2)

    end = time.time()
    print(f"Done in {end - start:.2f} seconds.")

if __name__ == "__main__":
    run_extraction()
