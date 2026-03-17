import pytesseract
from PIL import Image

def read_image(path):
    text = pytesseract.image_to_string(Image.open(path))

    numbers = []
    for t in text.split():
        if t.isdigit():
            numbers.append(int(t))

    return numbers[-20:]
