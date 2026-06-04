from django.contrib.auth.models import User
from django.db import models
from django.utils.crypto import get_random_string
from app.models.staffs import *



class StaffAccount(models.Model):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='staff_account')
    role = models.ForeignKey(Role, on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        if not self.user.username:
            first_initial = self.staff.first_name[0].upper()
            last_name = self.staff.last_name.lower()
            base_username = f"{first_initial}-{last_name}"
            unique_username = base_username
            counter = 1

            while User.objects.filter(username=unique_username).exists():
                unique_username = f"{base_username}{counter}"
                counter += 1

            self.user.username = unique_username
            self.user.set_password(get_random_string(12))

        if self.user.email != self.staff.email:
            self.user.email = self.staff.email
            self.user.save(update_fields=['email'])

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staff.first_name} {self.staff.last_name}"


