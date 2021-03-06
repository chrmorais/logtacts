import json
import logging
import re
from braces.views import LoginRequiredMixin
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.core.urlresolvers import reverse
from django.db.models import Case, Count, When
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import (
    get_object_or_404,
    redirect,
)
from django.views.generic import (
    ListView,
    FormView,
)

from django.utils import timezone
from haystack.generic_views import SearchView
from haystack.inputs import AutoQuery
from haystack.query import SearchQuerySet, SQ

from contacts.models import (
    Book,
    Contact,
    Tag,
    LogEntry,
)
from contacts import forms
from contacts.views import BookOwnerMixin

logger = logging.getLogger("loggly_logs")

class ContactListView(BookOwnerMixin, FormView, ListView):

    model = Contact
    template_name = 'contact_list.html'
    form_class = forms.MultiContactForm
    paginate_by = settings.LIST_PAGINATE_BY
    paginate_orphans = settings.LIST_PAGINATE_ORPHANS

    def get_search_contacts(self):
        book = self.request.current_book
        self.query_raw = self.request.GET.get('q')
        results = re.split(
            r'(?P<tag>\w+\:(?:\"[\w\s]+\"|\w+\b))',
            self.query_raw,
        )
        self.search_tags = []
        parts = []
        for result in results:
            if result.startswith('tag:'):
                tag_str = result.strip().split(':')[1].strip('"')
                try:
                    self.search_tags.append(Tag.objects.get(book=book, tag=tag_str))
                except Tag.DoesNotExist:
                    pass
            else:
                parts.append(result.strip())
        searchqueryset = SearchQuerySet().filter(book=book.id)
        if self.search_tags:
            searchqueryset = searchqueryset.filter(
                tags_ids__in=[tag.id for tag in self.search_tags],
            )

        self.query = ' '.join(parts).strip()
        sqs = searchqueryset.filter(
            SQ(name=AutoQuery(self.query)) | SQ(content=AutoQuery(self.query))
        )
        try:
            contact_ids = [result.object.id for result in sqs]
        except:
            contact_ids = []
        return contact_ids

    def get_success_url(self, *args, **kwargs):
        if not self.contact_ids:
            messages.info(self.request, "No contacts selected.")
            return reverse('contacts-list', kwargs={'book': self.request.current_book.id})
        if self.request.POST.get('emails'):
            return reverse('contact_emails', kwargs={'book': self.request.current_book.id})
        if self.request.POST.get('addresses'):
            return reverse('contact_addresses', kwargs={'book': self.request.current_book.id})
        if self.request.POST.get('merge'):
            return reverse('contacts_merge', kwargs={'book': self.request.current_book.id})
        if self.request.POST.get('addtag'):
            return reverse('contacts_add_tag', kwargs={'book': self.request.current_book.id})
        return reverse('contacts-list', kwargs={'book': self.request.current_book.id})

    def get_form_kwargs(self):
        kwargs = super(ContactListView, self).get_form_kwargs()
        kwargs['contact_ids'] = [contact.id for contact in self.get_queryset()]
        return kwargs

    def form_valid(self, form, *args, **kwargs):
        self.contact_ids = []
        for contact in form.cleaned_data:
            if form.cleaned_data[contact]:
                self.contact_ids.append(contact.split('_')[1])
        self.request.session['selected_contacts'] = json.dumps(self.contact_ids)
        
        return super(ContactListView, self).form_valid(form, *args, **kwargs)

    def get_queryset(self):
        if not (hasattr(self, '_queryset') and self._queryset):
            base_queryset = super(ContactListView, self).get_queryset()
            if self.request.GET.get('q'):
                search_contacts = self.get_search_contacts()
                preserved = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(search_contacts)])
                base_queryset = base_queryset.filter(
                    id__in=search_contacts
                ).order_by(preserved)
            self._queryset = base_queryset.annotate(has_last_contact=Count('last_contact'))
            sort = self.request.GET.get('s')
            if sort == 'oldnew':
                self._queryset = self._queryset.order_by('-has_last_contact','last_contact')
            if sort == 'newold':
                self._queryset = self._queryset.order_by('-has_last_contact','-last_contact')
            if sort == 'za':
                self._queryset = self._queryset.order_by('-name')
            if sort == 'az':
                self._queryset = self._queryset.order_by('name')
            if not self.request.GET.get('q') and not sort:
                self._queryset = self._queryset.order_by('-has_last_contact','-last_contact')
            self._queryset = self._queryset.prefetch_related('tags')
        return self._queryset

    def get_logs(self):
        return LogEntry.objects.logs_for_user_book(
            user=self.request.user,
            book=self.request.current_book,
        )

    def get_context_data(self, **kwargs):
        context = super(ContactListView, self).get_context_data(**kwargs)
        context['tags'] = Tag.objects.get_tags_for_user(
            user=self.request.user,
            book=self.request.current_book,
        )
        context['logs'] = self.get_logs()[:10]
        context['sort'] = self.request.GET.get('s')

        cache_key = cache_key = "{}::{}::random".format(self.request.user, self.request.current_book)
        if cache.get(cache_key):
            try:
                contact = Contact.objects.for_user(
                    user=self.request.user, book=self.request.current_book,
                ).get(id=cache.get(cache_key))
                last_day = timezone.now() - timedelta(days=1)
                if not contact.last_contact or contact.last_contact < last_day:
                    context['random_contact'] = contact
            except Contact.DoesNotExist:
                pass
        if self.request.GET.get('q'):
            context['search_tags'] = self.search_tags
            context['query_raw'] = self.query_raw
            context['query'] = self.query
            context['is_search'] = True
        return context


class TaggedContactListView(ContactListView):

    def dispatch(self, request, *args, **kwargs):
        self.tag = get_object_or_404(
            Tag.objects.get_tags_for_user(
                user=self.request.user,
                book=request.current_book,
            ),
            pk=self.kwargs.get('pk'),
        )
        return super(TaggedContactListView, self).dispatch(request, *args, **kwargs)

    def get_logs(self):
        return LogEntry.objects.logs_for_user_and_tag(
            user=self.request.user,
            tag=self.tag,
            book=self.request.current_book,
        ).order_by('-time')

    def get_queryset(self):
        return super(TaggedContactListView, self).get_queryset().filter(
            tags__id=self.kwargs.get('pk'),
        )

    def get_context_data(self, **kwargs):
        context = super(TaggedContactListView, self).get_context_data(**kwargs)
        context['tag'] = self.tag

        return context


class DailyRemindersView(ContactListView):

    def get_queryset(self):
        return super(DailyRemindersView, self).get_queryset().filter(
            reminder_frequency='daily',
        )

    def get_context_data(self, **kwargs):
        context = super(DailyRemindersView, self).get_context_data(**kwargs)
        context['reminder'] = 'Daily Reminders'

        return context


class WeeklyRemindersView(ContactListView):

    def get_queryset(self):
        return super(WeeklyRemindersView, self).get_queryset().filter(
            reminder_frequency='weekly',
        )

    def get_context_data(self, **kwargs):
        context = super(WeeklyRemindersView, self).get_context_data(**kwargs)
        context['reminder'] = 'Weekly Reminders'

        return context


class MonthlyRemindersView(ContactListView):

    def get_queryset(self):
        return super(MonthlyRemindersView, self).get_queryset().filter(
            reminder_frequency='monthly',
        )

    def get_context_data(self, **kwargs):
        context = super(MonthlyRemindersView, self).get_context_data(**kwargs)
        context['reminder'] = 'Monthly Reminders'

        return context


class QuarterlyRemindersView(ContactListView):

    def get_queryset(self):
        return super(QuarterlyRemindersView, self).get_queryset().filter(
            reminder_frequency='quarterly',
        )

    def get_context_data(self, **kwargs):
        context = super(QuarterlyRemindersView, self).get_context_data(**kwargs)
        context['reminder'] = 'Quarterly Reminders'

        return context
