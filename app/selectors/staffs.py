from app.models.staffs import Staff

def get_all_staffs():
    return Staff.objects.all()

def get_staff(id):
    return Staff.objects.get(pk=id)