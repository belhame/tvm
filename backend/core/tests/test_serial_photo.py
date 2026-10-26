"""Real fictional label images, bounded recognition and no business writes."""
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as Browser, SimpleTestCase, TestCase, override_settings
from PIL import Image
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.models import AuditLog, Client, Equipment, Intervention, ServiceRequest
from core.serial_photo import SerialPhotoDimensionsTooLarge, SerialPhotoTooLarge, recognize_serial_photo
from core.serial_photo_rules import barcode_serials, ocr_serials


FIXTURES = Path(__file__).parent / 'fixtures'
PHOTO_URL = '/api/logistics/recognize-serial/'


class SerialPhotoRuleTests(SimpleTestCase):
    def test_explicit_serial_labels_and_following_lines_are_supported(self):
        for label in ('S/N:', 'SN:', 'SERIAL NUMBER:', 'Serial No.', 'N° de série :'):
            with self.subTest(label=label):
                self.assertEqual(ocr_serials(f'{label} TVM-OCR-00042'), ['TVM-OCR-00042'])
                self.assertEqual(ocr_serials(f'{label}\n\nTVM-OCR-00042'), ['TVM-OCR-00042'])

    def test_model_power_phone_tax_and_part_numbers_are_not_serial_suggestions(self):
        text = 'MODEL: 9PX2200IRT2U\nINPUT: 230V 50HZ\nPHONE: +216 00 000 001\nMF: 0000000/A/M/000\nP/N: 9400-A000-00'
        self.assertEqual(ocr_serials(text), [])
        for value in ('9PX2200IRT2U', '3S850F', '230V', '1000VA', '21600000001', '9400-A000-00', 'P/N: 9400-A000-00'):
            with self.subTest(value=value):
                self.assertEqual(barcode_serials(value), [])
        self.assertEqual(ocr_serials('S/N:\nMF: 0000000/A/M/000'), [])

    def test_unlabelled_ocr_is_restricted_to_serial_shaped_ups_patterns(self):
        self.assertEqual(ocr_serials('AB12C34567\nmodel 93E20KVA\n120721-00000042'), ['AB12C34567', '120721-00000042'])
        self.assertEqual(ocr_serials('ABC123\n000000000000\ncontact@example.invalid'), [])

    def test_candidates_are_deduplicated_bounded_and_ambiguous_characters_not_fixed(self):
        text = '\n'.join(f'S/N: TVM-OCR-{index:05d}' for index in range(15))
        self.assertEqual(len(ocr_serials(text)), 10)
        self.assertEqual(ocr_serials('S/N: TVM-OCR-O0042\nSN: TVM-OCR-O0042'), ['TVM-OCR-O0042'])
        self.assertEqual(barcode_serials('https://example.invalid/device?serial=TVM-OCR-00042'), ['TVM-OCR-00042'])


class SerialPhotoEngineTests(SimpleTestCase):
    def test_real_code128_is_decoded_locally_without_ocr(self):
        result = recognize_serial_photo((FIXTURES / 'serial_barcode_fictif.png').read_bytes())
        self.assertEqual(result['candidates'], [{'serial_number': 'TVM-BAR-00042', 'source': 'barcode'}])
        self.assertEqual((result['status'], result['method']), ('recognized', 'barcode'))
        self.assertNotIn('confidence', result['candidates'][0])
        self.assertNotIn('raw_text', result)

    def test_real_two_barcodes_remain_ambiguous_for_the_user_to_choose(self):
        result = recognize_serial_photo((FIXTURES / 'serial_barcodes_ambigus_fictifs.png').read_bytes())
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual({item['serial_number'] for item in result['candidates']}, {'TVM-BAR-00042', 'TVM-BAR-00043'})

    @skipUnless(shutil.which('tesseract'), 'Tesseract local nécessaire pour le test OCR réel.')
    def test_actual_printed_label_without_barcode_is_read_by_tesseract(self):
        result = recognize_serial_photo((FIXTURES / 'serial_ocr_fictif.png').read_bytes())
        self.assertEqual(result['candidates'], [{'serial_number': 'TVM-OCR-00042', 'source': 'ocr'}])
        self.assertEqual((result['status'], result['method']), ('recognized', 'ocr'))

    @skipUnless(shutil.which('tesseract'), 'Tesseract local nécessaire pour le test OCR réel.')
    def test_jpeg_and_webp_are_actual_supported_photo_formats(self):
        with Image.open(FIXTURES / 'serial_ocr_fictif.png') as source:
            for image_format in ('JPEG', 'WEBP'):
                with self.subTest(image_format=image_format):
                    data = BytesIO()
                    source.save(data, image_format, quality=95)
                    result = recognize_serial_photo(data.getvalue())
                    self.assertEqual(result['candidates'], [{'serial_number': 'TVM-OCR-00042', 'source': 'ocr'}])

    def test_raster_validation_rejects_svg_pdf_gif_and_broken_data(self):
        gif = BytesIO()
        Image.new('RGB', (50, 50), 'white').save(gif, 'GIF')
        for data in (b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'%PDF-1.7', b'not-an-image', gif.getvalue()):
            with self.subTest(data=data[:20]), self.assertRaises(ValidationError):
                recognize_serial_photo(data)

    def test_oversized_file_and_pixel_dimensions_are_413(self):
        with self.assertRaises(SerialPhotoTooLarge):
            recognize_serial_photo(b'x' * (8 * 1024 * 1024 + 1))
        image = Image.new('L', (4000, 3001), 'white')
        data = BytesIO()
        image.save(data, 'PNG')
        with self.assertRaises(SerialPhotoDimensionsTooLarge):
            recognize_serial_photo(data.getvalue())

    def test_blank_photo_does_not_invent_a_number(self):
        image = Image.new('RGB', (400, 150), 'white')
        data = BytesIO()
        image.save(data, 'PNG')
        result = recognize_serial_photo(data.getvalue())
        self.assertIn(result['status'], ('not_found', 'unavailable'))
        self.assertEqual(result['candidates'], [])

    @skipUnless(shutil.which('tesseract'), 'Tesseract local nécessaire pour le test OCR réel.')
    def test_parent_cleans_all_temporary_images_and_ocr_files_after_real_recognition(self):
        folders = []
        def temporary(*args, **kwargs):
            instance = TemporaryDirectory(*args, **kwargs)
            folders.append(Path(instance.name))
            return instance
        with mock.patch('core.serial_photo.TemporaryDirectory', side_effect=temporary):
            result = recognize_serial_photo((FIXTURES / 'serial_ocr_fictif.png').read_bytes())
        self.assertEqual(result['status'], 'recognized')
        self.assertTrue(folders)
        self.assertTrue(all(not folder.exists() for folder in folders))

    def test_timeout_kills_the_process_group_and_cleans_the_private_folder(self):
        process = mock.Mock(pid=543210)
        process.communicate.side_effect = [subprocess.TimeoutExpired('worker', 5), (b'', None)]
        folders = []
        def temporary(*args, **kwargs):
            instance = TemporaryDirectory(*args, **kwargs)
            folders.append(Path(instance.name))
            return instance
        with mock.patch('core.serial_photo.TemporaryDirectory', side_effect=temporary), mock.patch('core.serial_photo.subprocess.Popen', return_value=process), mock.patch('core.serial_photo.os.killpg') as kill_group:
            result = recognize_serial_photo((FIXTURES / 'serial_ocr_fictif.png').read_bytes())
        self.assertEqual(result['status'], 'not_found')
        self.assertEqual(result['candidates'], [])
        self.assertTrue(all(not folder.exists() for folder in folders))
        if hasattr(__import__('os'), 'killpg'):
            kill_group.assert_called_once()

    def test_uploaded_exif_description_is_not_read_as_a_serial_number(self):
        with Image.open(FIXTURES / 'serial_barcode_fictif.png') as image:
            exif = Image.Exif()
            exif[270] = 'S/N: PRIVATE-EXIF-00099'
            data = BytesIO()
            image.convert('RGB').save(data, 'JPEG', quality=95, exif=exif)
        result = recognize_serial_photo(data.getvalue())
        self.assertEqual(result['candidates'], [{'serial_number': 'TVM-BAR-00042', 'source': 'barcode'}])
        self.assertNotIn('PRIVATE-EXIF', str(result))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SerialPhotoAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('photo-admin', role='admin')
        cls.manager = User.objects.create_user('photo-manager', role='manager')
        cls.courier = User.objects.create_user('photo-courier', role='courier')
        cls.tech = User.objects.create_user('photo-technician', role='technician')
        cls.company = Client.objects.create(name='Client fictif photo')
        cls.customer = User.objects.create_user('photo-client', role='client', client=cls.company)
    def setUp(self):
        self.api = APIClient()
    def photo(self):
        return SimpleUploadedFile('etiquette-fictive.png', (FIXTURES / 'serial_barcode_fictif.png').read_bytes(), content_type='image/png')

    def test_authorized_roles_read_real_barcode_without_any_business_write(self):
        models = (Client, Equipment, ServiceRequest, Intervention, AuditLog)
        before = [model.objects.count() for model in models]
        for actor in (self.admin, self.manager, self.courier):
            with self.subTest(role=actor.role):
                self.api.force_authenticate(actor)
                result = self.api.post(PHOTO_URL, {'file': self.photo()}, format='multipart')
                self.assertEqual(result.status_code, 200, result.data)
                self.assertEqual(result.data['candidates'], [{'serial_number': 'TVM-BAR-00042', 'source': 'barcode'}])
                self.assertIn('no-store', result['Cache-Control'])
        self.assertEqual([model.objects.count() for model in models], before)

    def test_client_technician_anonymous_and_inactive_accounts_cannot_start_processing(self):
        self.manager.is_active = False
        self.manager.save(update_fields=['is_active'])
        for actor in (self.customer, self.tech, None, self.manager):
            with self.subTest(actor=actor):
                self.api.force_authenticate(actor)
                with mock.patch('core.serial_photo_views.recognize_serial_photo') as recognize:
                    result = self.api.post(PHOTO_URL, {'file': self.photo()}, format='multipart')
                self.assertEqual(result.status_code, 403)
                recognize.assert_not_called()

    def test_no_mission_or_case_fields_can_be_smuggled_into_photo_reading(self):
        self.api.force_authenticate(self.admin)
        for extra in ({'mission': '42'}, {'action': 'receive'}, {'serial_number': 'FORGED-00042'}):
            with self.subTest(extra=extra):
                result = self.api.post(PHOTO_URL, {'file': self.photo(), **extra}, format='multipart')
                self.assertEqual(result.status_code, 400)

    def test_real_oversized_multipart_is_stopped_before_csrf_and_the_recognizer(self):
        browser = Browser(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        browser.get('/api/session/')
        photo = SimpleUploadedFile('too-large.png', b'x' * (8 * 1024 * 1024 + 1), content_type='image/png')
        with mock.patch('core.serial_photo_views.recognize_serial_photo') as recognize:
            response = browser.post(PHOTO_URL, {'file': photo}, HTTP_X_CSRFTOKEN=browser.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 413)
        recognize.assert_not_called()

    def test_content_length_guard_rejects_large_bodies_without_authentication(self):
        response = Browser(enforce_csrf_checks=True).generic('POST', PHOTO_URL, b'', content_type='multipart/form-data; boundary=lab', CONTENT_LENGTH=str(9 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)
