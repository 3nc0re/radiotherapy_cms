from django.db import migrations

def seed_protocols(apps, schema_editor):
    TreatmentProtocol = apps.get_model('patients', 'TreatmentProtocol')
    if not TreatmentProtocol.objects.exists():
        TreatmentProtocol.objects.create(
            name='🌸 Молочна залоза (15 фр × 2.67 Гр)',
            irradiation_zone='Молочна залоза',
            treatment_type='Ад\'ювантний',
            total_fractions=15,
            dose_per_fraction_raw='2.67',
            has_radiomodification=False
        )
        TreatmentProtocol.objects.create(
            name='🎯 Передміхурова залоза (39 фр × 2.0 Гр)',
            irradiation_zone='Передміхурова залоза',
            treatment_type='Радикальний',
            total_fractions=39,
            dose_per_fraction_raw='2.0',
            has_radiomodification=False
        )
        TreatmentProtocol.objects.create(
            name='🩺 Пряма кишка (5 фр × 5.0 Гр)',
            irradiation_zone='Пряма кишка',
            treatment_type='Неоад\'ювантний',
            total_fractions=5,
            dose_per_fraction_raw='5.0',
            has_radiomodification=False
        )
        TreatmentProtocol.objects.create(
            name='🧠 SIB Голова/Шия (33 фр × 2.0/2.2 Гр)',
            irradiation_zone='Голова та шия',
            treatment_type='Радикальний',
            total_fractions=33,
            dose_per_fraction_raw='2.0/2.2',
            has_radiomodification=True
        )
        TreatmentProtocol.objects.create(
            name='🦴 Паліатив кістки (5 фр × 4.0 Гр)',
            irradiation_zone='Кістки',
            treatment_type='Паліативний',
            total_fractions=5,
            dose_per_fraction_raw='4.0',
            has_radiomodification=False
        )

def unseed_protocols(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0020_treatmentprotocol'),
    ]

    operations = [
        migrations.RunPython(seed_protocols, unseed_protocols),
    ]
