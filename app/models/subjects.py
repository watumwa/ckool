from django.db import models
from django.urls import reverse

class Subject(models.Model):
    
    code = models.CharField(max_length=10)
    name = models.CharField(max_length=50)
    description = models.TextField(null=True, blank=True)
    credit_hours = models.IntegerField()
    section = models.ForeignKey("app.Section", on_delete=models.CASCADE)
    type = models.CharField(max_length=50, choices=[("Core", "Core"), ("Elective", "Elective")])

    class Meta:
        verbose_name = ("Subject")
        verbose_name_plural = ("Subjects")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("Subject_detail", kwargs={"pk": self.pk})


    