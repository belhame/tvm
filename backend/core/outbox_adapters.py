"""Timeout-bound provider adapters. Raw exceptions/responses are never logged."""
import json
import re
import smtplib
from email.utils import parseaddr
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.core.mail import EmailMessage, get_connection


class DeliveryFailure(Exception):
    def __init__(self, code, *, retryable=False, uncertain=False):
        super().__init__(code)
        self.code, self.retryable, self.uncertain = code, retryable, uncertain


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def deliver_email(recipient, context, delivery_key):
    domain = parseaddr(settings.DEFAULT_FROM_EMAIL)[1].rsplit('@', 1)[-1]
    message = EmailMessage(context['subject'], context['text'], settings.DEFAULT_FROM_EMAIL, [recipient],
        connection=get_connection(timeout=settings.EMAIL_TIMEOUT),
        headers={'Message-ID': f'<tvm-{delivery_key}@{domain}>'})
    try:
        if message.send(fail_silently=False) != 1:
            raise DeliveryFailure('smtp_not_accepted')
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused):
        raise DeliveryFailure('smtp_rejected') from None
    except smtplib.SMTPResponseException as exc:
        raise DeliveryFailure('smtp_rejected', retryable=400 <= exc.smtp_code < 500) from None
    except (TimeoutError, OSError, smtplib.SMTPServerDisconnected, smtplib.SMTPException):
        raise DeliveryFailure('smtp_acceptance_unknown', uncertain=True) from None
    return ''


def deliver_whatsapp(recipient, context, delivery_key):
    # Configuration validation permits only a numeric phone ID and API version;
    # neither a caller nor an environment URL can change the destination host.
    url = f'https://graph.facebook.com/{settings.TVM_WHATSAPP_API_VERSION}/{settings.TVM_WHATSAPP_PHONE_ID}/messages'
    body = {'messaging_product': 'whatsapp', 'to': recipient.lstrip('+'), 'type': 'template',
        'template': {'name': settings.TVM_WHATSAPP_TEMPLATE, 'language': {'code': settings.TVM_WHATSAPP_LANGUAGE},
                     'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': value} for value in context['template_values']]}]}}
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode(), method='POST', headers={
        'Authorization': f'Bearer {settings.TVM_WHATSAPP_TOKEN}', 'Content-Type': 'application/json'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=settings.TVM_NOTIFICATION_TIMEOUT) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise DeliveryFailure('whatsapp_acceptance_unknown', uncertain=True)
            data = json.loads(raw)
        identifier = data['messages'][0]['id']
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_.:=+/-]{1,200}', identifier):
            raise DeliveryFailure('whatsapp_acceptance_unknown', uncertain=True)
        return identifier
    except HTTPError as exc:
        if 500 <= exc.code < 600:
            raise DeliveryFailure('whatsapp_acceptance_unknown', uncertain=True) from None
        if exc.code == 429:
            try:
                error = json.loads(exc.read(65536)).get('error', {})
                explicit = type(error.get('code')) is int
            except (ValueError, TypeError, AttributeError):
                explicit = False
            if not explicit:
                raise DeliveryFailure('whatsapp_acceptance_unknown', uncertain=True) from None
            raise DeliveryFailure('whatsapp_rate_limited', retryable=True) from None
        raise DeliveryFailure('whatsapp_rejected') from None
    except (TimeoutError, OSError, URLError, ValueError, KeyError, IndexError, TypeError):
        raise DeliveryFailure('whatsapp_acceptance_unknown', uncertain=True) from None
