from app.models.students import *

def get_all_students():
    return Student.objects.all()

def get_student(id):
    return Student.objects.get(pk=id)
    

def get_active_students():
    
    return Student.objects.filter(is_active=True)


def get_inactive_students():

    return Student.objects.filter(is_active=False)