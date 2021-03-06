from datetime import timedelta
import factory

from django.utils import timezone
from common.factories import UserFactory
import contacts as contacts_constants
from . import models


class BookFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Book

    paid_until = timezone.now() + timedelta(weeks=1)


class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Contact

    name = "Philip James"
    book = factory.SubFactory(BookFactory)
    email = "philip+test@inkpebble.com"


class ContactFieldFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ContactField

    contact = factory.SubFactory(ContactFactory)
    kind = contacts_constants.FIELD_TYPE_EMAIL
    value = 'philip@contactotter.com'
    preferred = True

class BookOwnerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.BookOwner

    user = factory.SubFactory(UserFactory)
    book = factory.SubFactory(BookFactory)


class LogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.LogEntry

    contact = factory.SubFactory(ContactFactory)
    created = timezone.now()


class TagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Tag