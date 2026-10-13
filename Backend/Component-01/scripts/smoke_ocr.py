import os
from pathlib import Path

# Disable oneDNN (MKLDNN) and PIR conversion errors on CPU
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_enable_pir_in_executor"] = "0"

from paddleocr import PaddleOCR

# Initialize with use_textline_orientation
ocr = PaddleOCR(
    use_textline_orientation=True, 
    lang="en",
    enable_mkldnn=False,
)

image_path = Path(__file__).resolve().parent.parent / "data" / "samples" / "sample_invoice.png"

# Call predict
results = ocr.predict(str(image_path))

# Inspect and print the recognized text and confidence scores
for res in results:
    # Print raw structure to verify format for schemas
    print(res)