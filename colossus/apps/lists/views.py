from django.contrib.auth.decorators import login_required
from django.forms import modelform_factory
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView, DeleteView, DetailView, FormView, ListView, TemplateView,
    UpdateView, View,
)

from colossus.apps.subscribers.constants import Status, TemplateKeys
from colossus.apps.subscribers.models import (
    Subscriber, SubscriptionFormTemplate,
)

from .charts import SubscriptionsSummaryChart
from .forms import CSVImportSubscribersForm, PasteImportSubscribersForm
from .mixins import MailingListMixin
from .models import MailingList


@method_decorator(login_required, name='dispatch')
class MailingListListView(ListView):
    model = MailingList
    context_object_name = 'mailing_lists'
    ordering = ('name',)

    def get_context_data(self, **kwargs):
        kwargs['menu'] = 'lists'
        return super().get_context_data(**kwargs)


@method_decorator(login_required, name='dispatch')
class MailingListCreateView(CreateView):
    model = MailingList
    fields = ('name',)

    def get_context_data(self, **kwargs):
        kwargs['menu'] = 'lists'
        return super().get_context_data(**kwargs)


@method_decorator(login_required, name='dispatch')
class MailingListDetailView(DetailView):
    model = MailingList
    context_object_name = 'mailing_list'

    def get_context_data(self, **kwargs):
        kwargs['menu'] = 'lists'
        kwargs['submenu'] = 'details'
        return super().get_context_data(**kwargs)


@method_decorator(login_required, name='dispatch')
class SubscriberListView(MailingListMixin, ListView):
    model = Subscriber
    context_object_name = 'subscribers'
    paginate_by = 100
    template_name = 'lists/subscriber_list.html'

    def get_context_data(self, **kwargs):
        kwargs['submenu'] = 'subscribers'
        return super().get_context_data(**kwargs)

    def get_queryset(self):
        queryset = Subscriber.objects.filter(mailing_list_id=self.kwargs.get('pk')).order_by('optin_date')
        if 'q' in self.request.GET:
            query = self.request.GET.get('q')
            queryset = queryset.filter(email__icontains=query)
            self.extra_context = {
                'is_filtered': True,
                'query': query
            }
        return queryset


@method_decorator(login_required, name='dispatch')
class SubscriberCreateView(MailingListMixin, CreateView):
    model = Subscriber
    fields = ('email', 'name')
    template_name = 'lists/subscriber_form.html'

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.mailing_list_id = self.kwargs.get('pk')
        self.object.status = Status.SUBSCRIBED
        self.object.save()
        return redirect('lists:subscribers', pk=self.kwargs.get('pk'))


@method_decorator(login_required, name='dispatch')
class SubscriberUpdateView(MailingListMixin, UpdateView):
    model = Subscriber
    fields = '__all__'
    pk_url_kwarg = 'subscriber_pk'
    template_name = 'lists/subscriber_form.html'

    def get_success_url(self):
        return reverse('lists:subscribers', kwargs={'pk': self.kwargs.get('pk')})


@method_decorator(login_required, name='dispatch')
class SubscriberDeleteView(MailingListMixin, DeleteView):
    model = Subscriber
    pk_url_kwarg = 'subscriber_pk'
    context_object_name = 'subscriber'
    template_name = 'lists/subscriber_confirm_delete.html'

    def get_success_url(self):
        return reverse('lists:subscribers', kwargs={'pk': self.kwargs.get('pk')})


@method_decorator(login_required, name='dispatch')
class ImportSubscribersView(MailingListMixin, TemplateView):
    template_name = 'lists/import_subscribers.html'

    def get_context_data(self, **kwargs):
        kwargs['submenu'] = 'subscribers'
        return super().get_context_data(**kwargs)


@method_decorator(login_required, name='dispatch')
class AbstractImportSuscribersView(MailingListMixin, FormView):
    template_name = 'lists/import_subscribers_form.html'

    def get_context_data(self, **kwargs):
        kwargs['title'] = self.title
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        form.import_subscribers(self.request, self.kwargs.get('pk'))
        return redirect('lists:subscribers', pk=self.kwargs.get('pk'))


class CSVImportSubscribersView(AbstractImportSuscribersView):
    form_class = CSVImportSubscribersForm
    title = _('Import CSV File')


class PasteEmailsImportSubscribersView(AbstractImportSuscribersView):
    form_class = PasteImportSubscribersForm
    title = _('Paste Emails')


@method_decorator(login_required, name='dispatch')
class SubscriptionFormsView(MailingListMixin, TemplateView):
    template_name = 'lists/subscription_forms.html'

    def get_context_data(self, **kwargs):
        kwargs['submenu'] = 'forms'
        return super().get_context_data(**kwargs)


@method_decorator(login_required, name='dispatch')
class MailingListSettingsView(UpdateView):
    model = MailingList
    fields = ('name', 'slug', 'website_url', 'contact_email_address', 'campaign_default_from_name',
              'campaign_default_from_email', 'campaign_default_email_subject', 'enable_recaptcha', )
    context_object_name = 'mailing_list'
    template_name = 'lists/settings.html'

    def get_context_data(self, **kwargs):
        kwargs['menu'] = 'lists'
        kwargs['submenu'] = 'settings'
        return super().get_context_data(**kwargs)

    def get_success_url(self):
        return reverse('lists:settings', kwargs={'pk': self.kwargs.get('pk')})


@login_required
def charts_subscriptions_summary(request, pk):
    try:
        mailing_list = MailingList.objects.get(pk=pk)
        chart = SubscriptionsSummaryChart(mailing_list)
        return JsonResponse({'chart': chart.get_settings()})
    except MailingList.DoesNotExist:
        return JsonResponse(status_code=400)  # bad request status code


@method_decorator(login_required, name='dispatch')
class FormsEditorView(MailingListMixin, TemplateView):
    template_name = 'lists/forms_editor.html'


class FormTemplateMixin:
    def get_object(self):
        mailing_list_id = self.kwargs.get('pk')
        key = self.kwargs.get('form_key')
        if key not in TemplateKeys.LABELS.keys():
            raise Http404
        form_template, created = SubscriptionFormTemplate.objects.get_or_create(
            key=key,
            mailing_list_id=mailing_list_id
        )
        return form_template


@method_decorator(login_required, name='dispatch')
class SubscriptionFormTemplateUpdateView(FormTemplateMixin, MailingListMixin, UpdateView):
    model = SubscriptionFormTemplate
    template_name = 'lists/edit_form_template.html'
    context_object_name = 'form_template'

    def get_context_data(self, **kwargs):
        kwargs['template_keys'] = TemplateKeys
        return super().get_context_data(**kwargs)

    def get_template_names(self):
        return self.object.settings['admin_template_name']

    def get_form_class(self):
        fields = self.object.settings['fields']
        form_class = modelform_factory(self.model, fields=fields)
        return form_class

    def get_initial(self):
        initial = {
            'content_html': self.object.get_default_content()
        }
        return initial


@method_decorator(login_required, name='dispatch')
class PreviewFormTemplateView(FormTemplateMixin, MailingListMixin, View):
    def get(self, request, pk, form_key):
        form_template = self.get_object()
        template_name = form_template.settings['content_template_name']
        context = {
            'mailing_list': self.mailing_list,
            'contact_email': self.mailing_list.contact_email_address,
            'unsub': '#',
            'confirm_link': '#'
        }
        if form_key == TemplateKeys.SUBSCRIBE_PAGE:
            from colossus.apps.subscribers.forms import SubscribeForm
            context['form'] = SubscribeForm(mailing_list=self.mailing_list)
        elif form_key == TemplateKeys.UNSUBSCRIBE_PAGE:
            from colossus.apps.subscribers.forms import UnsubscribeForm
            context['form'] = UnsubscribeForm(mailing_list=self.mailing_list)
        return render(request, template_name, context)


@method_decorator(login_required, name='dispatch')
class CustomizeDesignView(UpdateView):
    model = MailingList
    fields = ('forms_custom_css', 'forms_custom_header')
    context_object_name = 'mailing_list'
    template_name = 'lists/customize_design.html'

    def get_context_data(self, **kwargs):
        kwargs['menu'] = 'lists'
        return super().get_context_data(**kwargs)

    def get_success_url(self):
        return reverse('lists:forms_editor', kwargs={'pk': self.kwargs.get('pk')})
