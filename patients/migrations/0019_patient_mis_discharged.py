from datetime import date
from django.db import migrations, models

def mark_past_patients_mis_discharged(apps, schema_editor):
    Patient = apps.get_model('patients', 'Patient')
    today = date(2026, 8, 18)
    Patient.objects.filter(models.Q(is_active=False) | models.Q(discharge_date__lt=today)).update(mis_discharged=True)

class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0018_patient_dose_per_fraction_raw_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='patient',
            name='mis_discharged',
            field=models.BooleanField(default=False, help_text='Виписано в МІС (eHealth)'),
        ),
        migrations.RunPython(mark_past_patients_mis_discharged, reverse_code=migrations.RunPython.noop),
    ]
