from io import BytesIO
import json
from types import SimpleNamespace
import subprocess
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from pypdf import PdfWriter
from reportlab.pdfgen import canvas
from rest_framework.exceptions import ValidationError

from core.attachment_validation import AttachmentTooLarge, MAX_FILE_SIZE
from core.knowledge_extraction import MAX_TEXT_CHARS, _pdf_pages, extract_uploaded_document
from core import knowledge_pdf_extract


def pdf_with_pages(texts):
    output = BytesIO()
    report = canvas.Canvas(output)
    for text in texts:
        if text is not None:
            report.drawString(30, 700, text)
        report.showPage()
    report.save()
    return output.getvalue()


def empty_pdf(*, encrypted=False):
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if encrypted:
        writer.encrypt('fictional-knowledge-test-password')
    writer.write(output)
    return output.getvalue()


class KnowledgeExtractionTests(SimpleTestCase):
    def test_utf8_txt_keeps_exact_text_and_source_hash(self):
        content = '\ufeffProcédure fictive\nMesurer 12 V avant réparation.\n'.encode('utf-8')
        result = extract_uploaded_document(SimpleUploadedFile('procedure.TXT', content))
        self.assertEqual(result['pages'], [{'page': 1, 'text': content.decode('utf-8-sig')}])
        self.assertEqual(result['page_count'], 1)
        self.assertEqual(result['text_status'], 'extracted')
        self.assertEqual(len(result['checked'].sha256), 64)
        self.assertEqual(result['checked'].data, content)

    def test_pdf_extracts_text_with_real_page_numbers(self):
        result = extract_uploaded_document(SimpleUploadedFile('manual.pdf', pdf_with_pages(['Synthetic manual first page', 'Synthetic manual second page'])))
        self.assertEqual(result['page_count'], 2)
        self.assertEqual([page['page'] for page in result['pages']], [1, 2])
        self.assertIn('first page', result['pages'][0]['text'])
        self.assertIn('second page', result['pages'][1]['text'])
        self.assertEqual(result['text_status'], 'extracted')
        self.assertTrue(any('images' in warning for warning in result['warnings']))

    def test_image_only_or_blank_pdf_does_not_claim_visual_reading(self):
        result = extract_uploaded_document(SimpleUploadedFile('schematic.pdf', empty_pdf()))
        self.assertEqual(result['text_status'], 'no_text')
        self.assertEqual(result['pages'], [{'page': 1, 'text': ''}])
        self.assertTrue(any('aucun OCR' in warning for warning in result['warnings']))
        self.assertTrue(any('lecture humaine' in warning for warning in result['warnings']))

    def test_some_empty_pdf_pages_are_explicitly_partial(self):
        result = extract_uploaded_document(SimpleUploadedFile('partial.pdf', pdf_with_pages(['Readable technical text', None])))
        self.assertEqual(result['text_status'], 'partial')
        self.assertEqual(result['page_count'], 2)
        self.assertEqual(result['pages'][1]['text'], '')
        self.assertTrue(any('Certaines pages' in warning for warning in result['warnings']))

    def test_whitespace_only_txt_is_not_retrievable_text(self):
        result = extract_uploaded_document(SimpleUploadedFile('empty-text.txt', b'  \n\t\n'))
        self.assertEqual(result['text_status'], 'no_text')

    def test_other_extensions_are_rejected_before_bytes_are_read(self):
        class ForbiddenUpload:
            name = 'not-allowed.docx'

            @property
            def size(self):
                raise AssertionError('A forbidden format must not be read')

            def chunks(self):
                raise AssertionError('A forbidden format must not be read')

        with self.assertRaises(ValidationError):
            extract_uploaded_document(ForbiddenUpload())

    def test_size_limit_is_the_existing_ten_mib_limit(self):
        with self.assertRaises(AttachmentTooLarge):
            extract_uploaded_document(SimpleUploadedFile('huge.txt', b'a' * (MAX_FILE_SIZE + 1)))

    def test_malformed_fake_pdf_and_invalid_utf8_txt_are_rejected(self):
        for name, data in [('manual.pdf', b'not a pdf'), ('manual.txt', b'\xff\xfe'), ('manual.txt', b'abc\x00def')]:
            with self.subTest(name=name, data=data), self.assertRaises(ValidationError):
                extract_uploaded_document(SimpleUploadedFile(name, data))

    def test_encrypted_pdf_remains_rejected(self):
        with self.assertRaises(ValidationError):
            extract_uploaded_document(SimpleUploadedFile('encrypted.pdf', empty_pdf(encrypted=True)))

    def test_txt_limits_reject_instead_of_silently_truncating(self):
        accepted = extract_uploaded_document(SimpleUploadedFile('at-limit.txt', b'A' * MAX_TEXT_CHARS))
        self.assertEqual(len(accepted['pages'][0]['text']), MAX_TEXT_CHARS)
        with self.assertRaises(ValidationError):
            extract_uploaded_document(SimpleUploadedFile('over-limit.txt', b'A' * (MAX_TEXT_CHARS + 1)))

    def test_real_pdf_per_page_text_limit(self):
        data = pdf_with_pages(['A' * 100_001])
        with self.assertRaises(ValidationError) as error:
            extract_uploaded_document(SimpleUploadedFile('long-page.pdf', data))
        self.assertIn('100 000', str(error.exception.detail))

    def test_real_pdf_total_text_limit(self):
        data = pdf_with_pages(['A' * 95_000] * 11)
        with self.assertRaises(ValidationError) as error:
            extract_uploaded_document(SimpleUploadedFile('many-long-pages.pdf', data))
        self.assertIn('1 000 000', str(error.exception.detail))

    def test_worker_timeout_is_reported_without_exception_or_source_content(self):
        with patch('core.knowledge_extraction.subprocess.run', side_effect=subprocess.TimeoutExpired('hidden-worker', 8)):
            with self.assertRaises(ValidationError) as error:
                _pdf_pages(b'PRIVATE-SOURCE-CONTENT')
        self.assertNotIn('PRIVATE', str(error.exception.detail))
        self.assertIn('limites', str(error.exception.detail))

    def test_worker_command_uses_fixed_module_limits_and_sanitized_environment(self):
        valid = {'valid': True, 'page_count': 1, 'pages': [{'page': 1, 'text': 'Technical text'}]}
        with patch('core.knowledge_extraction.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(valid).encode())) as run:
            self.assertEqual(_pdf_pages(b'%PDF-test')[0]['page'], 1)
        arguments = run.call_args
        self.assertEqual(arguments.args[0][-2:], ['-m', 'core.knowledge_pdf_extract'])
        self.assertEqual(arguments.kwargs['timeout'], 8)
        self.assertEqual(set(arguments.kwargs['env']), {'PATH', 'LANG', 'PYTHONDONTWRITEBYTECODE'})
        self.assertEqual(arguments.kwargs['stderr'], subprocess.DEVNULL)

    def test_worker_response_validation_rejects_untrusted_shape_and_text(self):
        cases = [
            {'valid': True, 'page_count': True, 'pages': [{'page': 1, 'text': 'text'}]},
            {'valid': True, 'page_count': 1, 'pages': [{'page': 2, 'text': 'text'}]},
            {'valid': True, 'page_count': 1, 'pages': [{'page': 1, 'text': 'text\x00'}]},
            {'valid': True, 'page_count': 1, 'pages': [{'page': 1, 'text': '\ud800'}]},
            {'valid': True, 'page_count': 1, 'pages': [{'page': 1, 'text': 'A' * 100_001}]},
            {'valid': True, 'page_count': 501, 'pages': []},
            {'valid': True, 'page_count': 1, 'pages': [{'page': 1, 'text': 'text', 'extra': 'forbidden'}]},
        ]
        for payload in cases:
            with self.subTest(payload=str(payload)[:120]):
                with patch('core.knowledge_extraction.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode())):
                    with self.assertRaises(ValidationError):
                        _pdf_pages(b'%PDF-test')

    def test_worker_killed_or_output_invalid_does_not_leak_internal_errors(self):
        for code, stdout in [(-9, b'PRIVATE WORKER ERROR'), (0, b'invalid JSON'), (0, b'[]')]:
            with patch('core.knowledge_extraction.subprocess.run', return_value=SimpleNamespace(returncode=code, stdout=stdout)):
                with self.assertRaises(ValidationError) as error:
                    _pdf_pages(b'%PDF-test')
                self.assertNotIn('PRIVATE', str(error.exception.detail))

    def test_worker_applies_cpu_memory_file_and_descriptor_limits(self):
        fake = SimpleNamespace(RLIMIT_CPU=1, RLIMIT_AS=2, RLIMIT_FSIZE=3, RLIMIT_NOFILE=4, setrlimit=Mock())
        with patch.dict('sys.modules', {'resource': fake}):
            knowledge_pdf_extract._limits()
        self.assertEqual(fake.setrlimit.call_count, 4)
        fake.setrlimit.assert_any_call(fake.RLIMIT_CPU, (5, 5))
        fake.setrlimit.assert_any_call(fake.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
        fake.setrlimit.assert_any_call(fake.RLIMIT_FSIZE, (0, 0))
