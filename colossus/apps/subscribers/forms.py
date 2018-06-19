from django import forms
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template import loader
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext

from colossus.utils import get_client_ip

from .constants import Status
from .models import Subscriber


class SubscribeForm(forms.ModelForm):
    class Meta:
        model = Subscriber
        fields = ('email',)

    def __init__(self, *args, **kwargs):
        self.mailing_list = kwargs.pop('mailing_list')
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        is_subscribed = Subscriber.objects \
            .filter(email__iexact=email, status=Status.SUBSCRIBED, mailing_list=self.mailing_list) \
            .exists()
        if is_subscribed:
            email_validation_error = ValidationError(
                gettext('The email address "%(email)s" is already subscribed to this list.'),
                params={'email': email},
                code='already_subscribed_error'
            )
            self.add_error('email', email_validation_error)
        return cleaned_data

    @transaction.atomic
    def subscribe(self, request):
        email = self.cleaned_data.get('email')
        subscriber, created = Subscriber.objects.get_or_create(email=email, mailing_list=self.mailing_list)
        subscriber.status = Status.PENDING
        subscriber.optin_ip_address = get_client_ip(request)
        subscriber.optin_date = timezone.now()
        subscriber.save()

        if not created:
            subscriber.tokens.filter(description='confirm_subscription').delete()

        token = subscriber.tokens.create(description='confirm_subscription')
        current_site = get_current_site(request)
        protocol = 'https' if request.is_secure() else 'http'
        domain = current_site.domain
        path = reverse('subscribers:confirm_double_optin_token', kwargs={
            'mailing_list_uuid': self.mailing_list.uuid,
            'token': token.text
        })
        confirm_link = '%s://%s%s' % (protocol, domain, path)

        context = {
            'confirm_link': confirm_link,
            'list_name': self.mailing_list.name,
            'contact_email': self.mailing_list.contact_email_address

        }

        subject = loader.render_to_string('subscribers/confirm_email_subject.txt', context)
        subject = ''.join(subject.splitlines())  # Email subject *must not* contain newlines
        plain_text_message = loader.render_to_string('subscribers/confirm_email.txt', context)
        rich_text_message = loader.render_to_string('subscribers/confirm_email.html', context)

        message = EmailMultiAlternatives(
            subject=subject,
            body=plain_text_message,
            to=[subscriber.get_email()]
        )
        message.attach_alternative(rich_text_message, 'text/html')
        message.send()

        return subscriber


class UnsubscribeForm(forms.Form):
    email = forms.EmailField()

    class Meta:
        fields = ('email',)

    def __init__(self, *args, **kwargs):
        self.mailing_list = kwargs.pop('mailing_list')
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        is_subscribed = Subscriber.objects.filter(
            email__iexact=email,
            mailing_list=self.mailing_list,
            status=Status.SUBSCRIBED
        )
        if not is_subscribed:
            email_validation_error = ValidationError(
                gettext('The email address "%(email)s" is not subscribed to this list.'),
                params={'email': email},
                code='not_subscribed_error'
            )
            self.add_error('email', email_validation_error)
        return cleaned_data

    def unsubscribe(self, request):
        email = self.cleaned_data.get('email')
        subscriber = Subscriber.objects.get(email=email, mailing_list=self.mailing_list)
        subscriber.unsubscribe(request)
