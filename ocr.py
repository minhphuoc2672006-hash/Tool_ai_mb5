import pytesseract
from PIL import Image

def read_image(path):
    try:
        img = Image.open(path)
        text = pytesseract.image_to_string(img)

        numbers = []
        for t in text.split():
            if t.isdigit():
                numbers.append(int(t))

        return numbers[-20:]

    except Exception as e:
        print("OCR ERROR:", e)
        return []
