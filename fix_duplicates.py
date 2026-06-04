#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from django.db import models
from app.models.classes import ClassSubjectAllocation

# Find duplicates
duplicates = ClassSubjectAllocation.objects.values('academic_class_stream', 'subject').annotate(
    count=models.Count('id')
).filter(count__gt=1)

print('Duplicate combinations found:', duplicates.count())

if duplicates.count() == 0:
    print("No duplicates! The migration should work now.")
else:
    print('\nRemoving duplicates...')
    
    # Keep the first record, delete the rest for each duplicate combination
    for d in duplicates:
        allocs = list(ClassSubjectAllocation.objects.filter(
            academic_class_stream_id=d['academic_class_stream'],
            subject_id=d['subject']
        ).order_by('id'))
        
        # Keep first, delete rest
        keep = allocs[0]
        delete_count = len(allocs) - 1
        
        ClassSubjectAllocation.objects.filter(
            academic_class_stream_id=d['academic_class_stream'],
            subject_id=d['subject']
        ).exclude(id=keep.id).delete()
        
        print(f'  Stream {d["academic_class_stream"]}, Subject {d["subject"]}: kept ID {keep.id}, deleted {delete_count}')
    
    print('\nDuplicates removed! Run migration again.')
