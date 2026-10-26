"""Generate clearly fictional scan fixtures; never use customer photographs."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import reportlab
import zxingcpp


def build(folder):
    font_path = Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf'
    code = zxingcpp.create_barcode('TVM-BAR-00042', zxingcpp.BarcodeFormat.Code128)
    barcode = Image.fromarray(zxingcpp.write_barcode_to_image(code, scale=3))
    image = Image.new('RGB', (max(700, barcode.width + 100), barcode.height + 150), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 25)
    draw.text((40, 15), 'FICTIF - ETIQUETTE DE TEST TVM', fill='black', font=font)
    image.paste(barcode, (50, 65))
    draw.text((50, barcode.height + 80), 'S/N: TVM-BAR-00042', fill='black', font=font)
    image.save(folder / 'serial_barcode_fictif.png', 'PNG')
    (folder / 'serial_barcode_fictif.png').chmod(0o644)
    second_code = zxingcpp.create_barcode('TVM-BAR-00043', zxingcpp.BarcodeFormat.Code128)
    second = Image.fromarray(zxingcpp.write_barcode_to_image(second_code, scale=3))
    pair = Image.new('RGB', (image.width, image.height * 2), 'white')
    pair.paste(image, (0, 0))
    pair.paste(second, (50, image.height + 40))
    draw_pair = ImageDraw.Draw(pair)
    draw_pair.text((50, image.height + second.height + 55), 'S/N: TVM-BAR-00043', fill='black', font=font)
    pair.save(folder / 'serial_barcodes_ambigus_fictifs.png', 'PNG')
    (folder / 'serial_barcodes_ambigus_fictifs.png').chmod(0o644)
    image = Image.new('RGB', (1200, 420), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 42)
    for y, text in ((40, 'UPS LABEL - FICTIONAL'), (120, 'S/N: TVM-OCR-00042'),
                    (205, 'MODEL: 93E 20KVA'), (285, 'INPUT: 230V 50HZ')):
        draw.text((60, y), text, font=font, fill='black')
    image.save(folder / 'serial_ocr_fictif.png', 'PNG')
    (folder / 'serial_ocr_fictif.png').chmod(0o644)


if __name__ == '__main__':
    build(Path(__file__).resolve().parent)
