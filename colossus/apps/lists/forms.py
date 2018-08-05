from smtplib import SMTPAuthenticationError

from django import forms
from django.core.exceptions import ValidationError
from django.core.mail.backends.smtp import EmailBackend
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from colossus.apps.lists.constants import ImportStatus
from colossus.apps.lists.tasks import import_subscribers
from colossus.apps.subscribers.constants import ActivityTypes, Status
from colossus.apps.subscribers.models import Subscriber

from .models import MailingList, SubscriberImport


class ConfirmSubscriberImportForm(forms.ModelForm):
    """
    Form used to define what status will be assigned to the imported subscribers
    and the import strategy (update or create, or create only).

    After saving the form, place the csv import file in the queue to be
    processed by a Celery task.
    """
    class Meta:
        model = SubscriberImport
        fields = ('subscriber_status', 'update_or_create')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import_fields = list()
        for field in SubscriberImport.DEFAULT_IMPORT_TEMPLATE:
            import_fields.append((field[0], field[1]))

        choices = (('', _('--- Ignore column ---'),),) + tuple(import_fields)
        self.headings = self.instance.get_headings()
        columns_mapping = self.instance.get_columns_mapping()
        if not columns_mapping:
            columns_mapping = list(map(lambda field: field[0], import_fields))
        for index, heading in enumerate(self.headings):
            self.fields[self._field_key(index)] = forms.ChoiceField(
                label=heading,
                required=False,
                choices=choices
            )
            try:
                self.initial[self._field_key(index)] = columns_mapping[index]
            except (KeyError, IndexError):
                pass

    def _field_key(self, index: int):
        return f'__column_{index}'

    def column_mapping_fields(self):
        return [field for field in self if field.name.startswith('__column_')]

    def import_settings_fields(self):
        return [field for field in self.visible_fields() if not field.name.startswith('__column_')]

    def queue(self):
        import_subscribers.delay(self.instance.pk)

    def save(self, commit=True):
        subscriber_import: SubscriberImport = super().save(commit=False)
        subscriber_import.status = ImportStatus.QUEUED
        if commit:
            subscriber_import.save(update_fields=['subscriber_status', 'update_or_create', 'status'])
            self.queue()
        return subscriber_import


class PasteImportSubscribersForm(forms.Form):
    emails = forms.CharField(
        label=_('Paste email addresses'),
        help_text=_('One email per line, or separated by comma. Duplicate emails will be suppressed.'),
        widget=forms.Textarea()
    )
    status = forms.ChoiceField(
        label=_('Assign status to subscriber'),
        choices=Status.CHOICES,
        initial=Status.SUBSCRIBED,
        widget=forms.Select(attrs={'class': 'w-50'})
    )

    def clean(self):
        """
        First replace the commas with new lines, then split the text by lines.
        This is done so to accept both a string of emails separated by new lines
        or by commas.
        Normalize the email addresses inside a loop and call the email validator
        for each email.
        Emails are added to a dictionary so to remove the duplicates and at the
        same time preserve the case informed. The dictionary key is the lower
        case of the email, and the value is its original form.
        After the code iterates through all the emails, return only the values
        of the dictionary.
        """
        cleaned_data = super().clean()
        emails = self.cleaned_data.get('emails', '')
        emails = emails.replace(',', '\n').splitlines()
        cleaned_emails = dict()
        for email in emails:
            email = Subscriber.objects.normalize_email(email)
            validate_email(email)
            cleaned_emails[email.lower()] = email
        cleaned_data['emails'] = cleaned_emails.values()
        return cleaned_data

    def import_subscribers(self, mailing_list):
        emails = self.cleaned_data.get('emails')
        status = self.cleaned_data.get('status')
        with transaction.atomic():
            for email in emails:
                subscriber, created = Subscriber.objects.get_or_create(
                    email__iexact=email,
                    mailing_list=mailing_list,
                    defaults={
                        'email': email,
                    }
                )
                if created:
                    subscriber.create_activity(ActivityTypes.IMPORTED)
                subscriber.status = status
                subscriber.update_date = timezone.now()
                subscriber.save()
            mailing_list.update_subscribers_count()


class ColumnsMappingForm(forms.ModelForm):
    FIELDS = {
        'email': _('Email address'),
        'name': _('Name'),
        'open_rate': _('Open rate'),
        'click_rate': _('Click rate'),
        'update_date': _('Update date'),
        'optin_ip_address': _('Opt-in IP address'),
        'optin_date': _('Opt-in date'),
        'confirm_ip_address': _('Confirm IP address'),
        'confirm_date': _('Confirm date')
    }

    class Meta:
        model = SubscriberImport
        fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = (('', _('Select...'),),) + tuple(self.FIELDS.items())
        sample_data = self.instance.get_rows(limit=1)[0]
        self.headings = self.instance.get_headings()
        columns_mapping = self.instance.get_columns_mapping()
        if not columns_mapping:
            columns_mapping = list(self.FIELDS.keys())
        self._key = lambda i: '__column_%s' % i
        for index, heading in enumerate(self.headings):
            self.fields[self._key(index)] = forms.ChoiceField(
                label=heading,
                required=False,
                choices=choices,
                help_text=_('Sample data: "%s"') % sample_data[index]
            )
            try:
                self.initial[self._key(index)] = columns_mapping[index]
            except (KeyError, IndexError):
                pass

    def clean(self):
        cleaned_data = super().clean()
        for index, heading in enumerate(self.headings):
            if cleaned_data.get(self._key(index), '') == 'email':
                break
        else:
            email_column_required = ValidationError(
                gettext('At least one column should map to "Email address" field.'),
                code='email_column_required'
            )
            self.add_error(None, email_column_required)
        return cleaned_data

    def save(self, commit=True):
        subscriber_import = super().save(commit=False)
        mapping = dict()
        for index, heading in enumerate(self.headings):
            value = self.cleaned_data.get(self._key(index), '')
            if value:
                mapping[index] = value
        subscriber_import.set_columns_mapping(mapping)
        if commit:
            subscriber_import.save()
        return subscriber_import


class MailingListSMTPForm(forms.ModelForm):
    class Meta:
        model = MailingList
        fields = ('smtp_host', 'smtp_port', 'smtp_username', 'smtp_password', 'smtp_use_tls', 'smtp_use_ssl',
                  'smtp_timeout', 'smtp_ssl_keyfile', 'smtp_ssl_certfile')

    def clean(self):
        cleaned_data = super().clean()
        smtp_email_backend = EmailBackend(
            host=cleaned_data.get('smtp_host'),
            port=cleaned_data.get('smtp_port'),
            username=cleaned_data.get('smtp_username'),
            password=cleaned_data.get('smtp_password'),
            use_tls=cleaned_data.get('smtp_use_tls'),
            fail_silently=False,
            use_ssl=cleaned_data.get('smtp_use_ssl'),
            timeout=cleaned_data.get('smtp_timeout'),
            ssl_keyfile=cleaned_data.get('smtp_ssl_keyfile'),
            ssl_certfile=cleaned_data.get('smtp_ssl_certfile')
        )
        try:
            smtp_email_backend.open()
        except ConnectionRefusedError:
            raise ValidationError(_('Connection refused'), code='connection_refused')
        except SMTPAuthenticationError as err:
            raise ValidationError(str(err), code='auth_error')
        return cleaned_data
