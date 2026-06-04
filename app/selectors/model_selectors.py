
def get_all_model_records(model):
    return model.objects.all()

def get_model_record(model, id):
    return model.objects.get(pk=id)

def get_model_filtered_records(model, instance):
    return model.objects.filter(instance=instance)