from django.apps import apps
from django.db import transaction

from celery import shared_task

from colossus.apps.subscribers.constants import ActivityTypes


@shared_task
def update_open_rate(subscriber_id, email_id):
    Subscriber = apps.get_model('subscribers', 'Subscriber')
    Email = apps.get_model('campaigns', 'Email')
    try:
        subscriber = Subscriber.objects.filter(pk=subscriber_id).select_related('mailing_list').get()
        email = Email.objects.filter(pk=email_id).select_related('campaign').get()
        with transaction.atomic():
            subscriber.update_open_rate()
            subscriber.mailing_list.update_open_rate()
            email.update_opens_count()
            email.campaign.update_opens_count_and_rate()
    except (Subscriber.DoesNotExist, Email.DoesNotExist):
        pass  # TODO: log exceptions


@shared_task
def update_click_rate(subscriber_id, link_id):
    Subscriber = apps.get_model('subscribers', 'Subscriber')
    Link = apps.get_model('campaigns', 'Link')
    try:
        subscriber = Subscriber.objects.filter(pk=subscriber_id).select_related('mailing_list').get()
        link = Link.objects.filter(pk=link_id).select_related('email__campaign').get()
        with transaction.atomic():
            if not subscriber.activities.filter(activity_type=ActivityTypes.OPENED, email=link.email).exists():
                # For the user to click on the email, he/she must have opened it. In some cases the open pixel won't
                # be triggered. So in those cases, force an open record
                activity = subscriber.activities.filter(activity_type=ActivityTypes.CLICKED, link=link).first()
                ip_address = activity.ip_address if activity is not None else None
                subscriber.open(link.email, ip_address)
            subscriber.update_click_rate()
            subscriber.mailing_list.update_click_rate()
            link.update_clicks_count()
            link.email.update_clicks_count()
            link.email.campaign.update_clicks_count_and_rate()
    except (Subscriber.DoesNotExist, Link.DoesNotExist):
        pass  # TODO: log exceptions
