from django.views.generic import CreateView, ListView, DetailView, UpdateView, FormView, TemplateView, View
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string

from .api import get_test_email_context
from .models import Campaign, Email
from .mixins import CampaignMixin
from .forms import DesignEmailForm, PlainTextEmailForm, CampaignTestEmailForm
from .tasks import send_campaign_task


class CampaignListView(CampaignMixin, ListView):
    model = Campaign
    context_object_name = 'campaigns'
    paginate_by = 3


class CampaignCreateView(CampaignMixin, CreateView):
    model = Campaign
    fields = ('campaign_type', 'name',)


class CampaignEditView(CampaignMixin, DetailView):
    model = Campaign
    context_object_name = 'campaign'
    template_name = 'campaigns/campaign_edit.html'

    def get_context_data(self, **kwargs):
        kwargs['test_email_form'] = CampaignTestEmailForm()
        kwargs['plain_text_email_form'] = PlainTextEmailForm(instance=self.object.email)
        kwargs['checklist'] = self.object.email.checklist()
        return super().get_context_data(**kwargs)


class CampaignDetailView(CampaignMixin, DetailView):
    model = Campaign
    context_object_name = 'campaign'


class CampaignEditRecipientsView(CampaignMixin, UpdateView):
    model = Campaign
    fields = ('mailing_list',)
    context_object_name = 'campaign'

    def get_context_data(self, **kwargs):
        kwargs['title'] = 'Recipients'
        return super().get_context_data(**kwargs)


class AbstractCampaignEmailUpdateView(CampaignMixin, UpdateView):
    model = Email
    template_name = 'campaigns/campaign_form.html'

    def get_context_data(self, **kwargs):
        kwargs['title'] = self.title
        kwargs['campaign'] = self.campaign
        return super().get_context_data(**kwargs)

    def get_object(self, queryset=None):
        self.campaign = get_object_or_404(Campaign, pk=self.kwargs.get('pk'))
        return self.campaign.email

    def get_success_url(self):
        return reverse('campaigns:campaign_edit', kwargs=self.kwargs)


class CampaignEditFromView(AbstractCampaignEmailUpdateView):
    title = 'From'
    fields = ('from_name', 'from_email',)


class CampaignEditSubjectView(AbstractCampaignEmailUpdateView):
    title = 'Subject'
    fields = ('subject', 'preview',)


class CampaignEditContentView(AbstractCampaignEmailUpdateView):
    title = 'Design Email'
    form_class = DesignEmailForm
    template_name = 'campaigns/design_email_form.html'


class CampaignEditPlainTextContentView(AbstractCampaignEmailUpdateView):
    title = 'Edit Plain-Text Email'
    form_class = PlainTextEmailForm


def campaign_test_email(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if request.method == 'POST':
        form = CampaignTestEmailForm(request.POST)
        if form.is_valid():
            form.send(campaign.email)
            return redirect(campaign.get_absolute_url())
    else:
        form = CampaignTestEmailForm()
    return render(request, 'campaigns/test_email_form.html', {
        'menu': 'campaigns',
        'campaign': campaign,
        'form': form
    })


def campaign_preview_email(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if request.method == 'POST':
        campaign.email.content = request.POST.get('content')
    test_context_dict = get_test_email_context()
    html = campaign.email.render_html(test_context_dict)
    if 'application/json' in request.META.get('HTTP_ACCEPT'):
        return JsonResponse({'html': html})
    else:
        return HttpResponse(html)


class SendCampaignView(CampaignMixin, View):
    def get(self, request, pk):
        campaign = get_object_or_404(Campaign, pk=pk)
        return render(request, 'campaigns/send_campaign.html', {'campaign': campaign})

    def post(self, request, pk):
        campaign = get_object_or_404(Campaign, pk=pk)
        campaign.send()
        return redirect('campaigns:send_campaign_complete', pk=pk)


class SendCampaignCompleteView(CampaignMixin, DetailView):
    model = Campaign
    context_object_name = 'campaign'
    template_name = 'campaigns/send_campaign_done.html'
