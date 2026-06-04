from django.db import models
from django.conf import settings
from django.utils import timezone
from app.constants import AUDIENCE_CHOICES



class Announcement(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default="all")
    priority = models.CharField(
        max_length=10,
        choices=[("low", "Low"), ("normal", "Normal"), ("high", "High")],
        default="normal",
    )
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_announcements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_at", "-created_at"]

    def __str__(self):
        return self.title


class AnnouncementTarget(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="targets")
    staff = models.ForeignKey("app.Staff", on_delete=models.CASCADE, related_name="targeted_announcements")

    class Meta:
        unique_together = ("announcement", "staff")

    def __str__(self):
        return f"{self.announcement} -> {self.staff}"


class Event(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default="all")
    location = models.CharField(max_length=120, blank=True)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_datetime", "title"]

    def __str__(self):
        return self.title


class MessageThread(models.Model):
    subject = models.CharField(max_length=200, blank=True)
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="message_threads")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_threads",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.subject or f"Thread {self.pk}"


class Message(models.Model):
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Message {self.pk}"


class MessageThreadArchive(models.Model):
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="archive_entries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="archived_message_threads")
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("thread", "user")

    def __str__(self):
        return f"{self.thread} archived by {self.user}"
