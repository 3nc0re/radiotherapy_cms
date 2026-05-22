from django.db import migrations
from datetime import date

def migrate_patient_data(apps, schema_editor):
    Patient = apps.get_model('patients', 'Patient')
    today = date.today()
    for patient in Patient.objects.all():
        # Migrate gender
        if patient.gender == 'Ч':
            patient.gender = 'M'
        elif patient.gender == 'Ж':
            patient.gender = 'F'
            
        # Migrate hospitalization status
        if patient.inpatient_status == 'стаціонарно':
            patient.hospitalization_status = 'inpatient'
        elif patient.inpatient_status == 'амбулаторно':
            patient.hospitalization_status = 'outpatient'
        else:
            patient.hospitalization_status = 'outpatient'
            
        # Set is_active based on discharge date
        if patient.discharge_date and patient.discharge_date < today:
            patient.is_active = False
        else:
            patient.is_active = True
            
        patient.save()

def reverse_migrate_patient_data(apps, schema_editor):
    Patient = apps.get_model('patients', 'Patient')
    for patient in Patient.objects.all():
        # Reverse gender
        if patient.gender == 'M':
            patient.gender = 'Ч'
        elif patient.gender == 'F':
            patient.gender = 'Ж'
            
        # Reverse hospitalization status
        if patient.hospitalization_status == 'inpatient':
            patient.inpatient_status = 'стаціонарно'
        elif patient.hospitalization_status == 'outpatient':
            patient.inpatient_status = 'амбулаторно'
            
        patient.save()

class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0009_patient_bed_owner_patient_hospitalization_status_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_patient_data, reverse_migrate_patient_data),
    ]
