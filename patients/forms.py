from django import forms
from django.core.exceptions import ValidationError
from .models import Patient, FractionHistory, MedicalIncapacity, User
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import authenticate

class PatientForm(forms.ModelForm):
    birth_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    histology_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    ct_simulation_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    treatment_start_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    discharge_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    last_blood_test_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    planned_admission_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    dose_per_fraction = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'напр. 2.0 або 2.66/3.0 (SIB)'}),
        help_text="Доза на фракцію (Гр). Для SIB вкажуйте через слеш: 2.66/3.0"
    )
    received_dose = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'напр. 50.0'}),
        help_text="Отримана доза / СОД (Гр)"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Форматуємо дати для відображення в полях
        date_fields = ['birth_date', 'histology_date', 'ct_simulation_date', 
                      'treatment_start_date', 'discharge_date', 'last_blood_test_date', 'planned_admission_date']
        for field_name in date_fields:
            if self.instance.pk and getattr(self.instance, field_name):
                date_value = getattr(self.instance, field_name)
                if date_value:
                    self.initial[field_name] = date_value.strftime('%d.%m.%Y')
        
        if self.instance.pk:
            if self.instance.received_dose is not None:
                self.initial['received_dose'] = f"{self.instance.received_dose:g}"
            if self.instance.dose_per_fraction_raw:
                self.initial['dose_per_fraction'] = self.instance.dose_per_fraction_raw
            elif self.instance.dose_per_fraction is not None:
                if self.instance.is_sib and self.instance.dose_per_fraction_secondary is not None:
                    self.initial['dose_per_fraction'] = f"{self.instance.dose_per_fraction:g}/{self.instance.dose_per_fraction_secondary:g}"
                else:
                    self.initial['dose_per_fraction'] = f"{self.instance.dose_per_fraction:g}"

    auto_confirm_past_fractions = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Автоматично відмітити фракції до сьогодні як отримані (якщо дата початку лікування в минулому)"
    )

    def clean_dose_per_fraction(self):
        val = self.cleaned_data.get('dose_per_fraction')
        if not val:
            return None
        val_str = str(val).strip().replace(',', '.')
        if '/' in val_str:
            parts = [p.strip() for p in val_str.split('/') if p.strip()]
            if len(parts) != 2:
                raise ValidationError("Для SIB вкажіть дві дози через слеш (наприклад: 2.66/3.0)")
            try:
                float(parts[0])
                float(parts[1])
            except ValueError:
                raise ValidationError("Введіть коректні числові дози (наприклад: 2.66/3.0)")
            return f"{parts[0]}/{parts[1]}"
        else:
            try:
                float(val_str)
                return val_str
            except ValueError:
                raise ValidationError("Введіть числову дозу (наприклад: 8.0 або 2.66/3.0)")

    def clean_received_dose(self):
        val = self.cleaned_data.get('received_dose')
        if not val:
            return None
        val_str = str(val).strip().replace(',', '.')
        try:
            return float(val_str)
        except ValueError:
            raise ValidationError("Введіть числову дозу СОД (наприклад: 50.0)")

    def save(self, commit=True):
        patient = super().save(commit=False)
        raw_dose = self.cleaned_data.get('dose_per_fraction')
        patient.parse_and_set_doses(raw_dose)
        patient.received_dose = self.cleaned_data.get('received_dose')
        if commit:
            patient.save()
            self.save_m2m()
            # Якщо дата старту в минулому і стоїть галочка автопідтвердження
            if self.cleaned_data.get('auto_confirm_past_fractions') and patient.treatment_start_date:
                from django.utils import timezone
                from .services import generate_fractions_for_patient
                if not patient.fractions.exists() and patient.total_fractions and patient.dose_per_fraction:
                    generate_fractions_for_patient(patient)
                today = timezone.localdate()
                patient.fractions.filter(date__lte=today, status='scheduled').update(status='delivered')
                patient.recalculate_received_dose()
                patient.save()
        return patient
    
    class Meta:
        model = Patient
        fields = [
            'ambulatory_card_id', 'last_name', 'first_name', 'middle_name', 'birth_date', 'gender',
            'diagnosis', 'tnm_staging', 'disease_stage', 'clinical_group', 
            'treatment_type', 'histology_number', 'histology_date',
            'histology_description', 'ct_simulation_date', 'treatment_start_date',
            'total_fractions',
            'discharge_date', 'raw_diagnosis', 'has_radiomodification',
            'irradiation_zone', 'hospitalization_status', 'planned_admission_date',
            'bed_owner', 'ward_number', 'prior_radiation', 
            'last_blood_test_date', 'notes'
        ]
        widgets = {
            'ambulatory_card_id': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Наприклад: 228435/2025 або 2025-9246582',
                'pattern': '[0-9/\\-]+',
                'title': 'Дозволені тільки цифри, слеш (/) та дефіс (-)'
            }),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть прізвище'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть ім\'я'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть по батькові'}),
            'gender': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('', 'Виберіть стать'),
                ('M', 'Чоловіча'),
                ('F', 'Жіноча')
            ]),
            'diagnosis': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть діагноз'}),
            'tnm_staging': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Наприклад: T2N0M0'}),
            'disease_stage': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть стадію (напр. IIIB)'}),
            'clinical_group': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть клінічну групу'}),
            'treatment_type': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('', 'Виберіть тип лікування'),
                ('радикальне', 'Радикальне'),
                ('паліативне', 'Паліативне'),
                ('симптоматичне', 'Симптоматичне')
            ]),
            'histology_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Номер гістології'}),
            'histology_description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Опис гістологічного дослідження'}),
            'treatment_start_date': forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'}),
            'total_fractions': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': 'Кількість фракцій'}),
            'dose_per_fraction': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': 0.01, 'placeholder': 'Доза на фракцію (Гр)'}),
            'received_dose': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': 0.01, 'placeholder': 'Отримана доза (Гр)'}),
            'missed_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': 'Пропущені дні'}),
            'discharge_date': forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'}),
            'current_stage': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('', 'Виберіть етап'),
                ('КТ-симуляція', 'КТ-симуляція'),
                ('початок лікування', 'Початок лікування'),
                ('лікування', 'Лікування'),
                ('виписка', 'Виписка')
            ]),
            'has_radiomodification': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'raw_diagnosis': forms.HiddenInput(),
            'irradiation_zone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Зона опромінення'}),
            'hospitalization_status': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('outpatient', 'Амбулаторно'),
                ('inpatient', 'Стаціонар'),
                ('queue', 'У черзі')
            ]),
            'planned_admission_date': forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'}),
            'bed_owner': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть прізвище лікаря'}),
            'ward_number': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Номер палати'}),
            'prior_radiation': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Попереднє опромінення'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Додаткові примітки'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        import re
        
        # Валідація ambulatory_card_id
        ambulatory_card_id = cleaned_data.get('ambulatory_card_id')
        if ambulatory_card_id:
            # Видаляємо пробіли на початку та в кінці
            ambulatory_card_id = ambulatory_card_id.strip()
            cleaned_data['ambulatory_card_id'] = ambulatory_card_id
            
            # Перевірка формату: дозволені тільки цифри, / та -
            pattern = r'^[0-9/\\-]+$'
            if not re.match(pattern, ambulatory_card_id):
                raise ValidationError({
                    'ambulatory_card_id': 'ID амбулаторної картки може містити тільки цифри, слеш (/) та дефіс (-)'
                })
            
            # Перевірка, що є хоча б одна цифра
            if not re.search(r'\d', ambulatory_card_id):
                raise ValidationError({
                    'ambulatory_card_id': 'ID амбулаторної картки повинен містити хоча б одну цифру'
                })
            
            # Перевірка унікальності (якщо редагуємо існуючого пацієнта)
            instance = self.instance
            if instance and instance.pk:
                existing = Patient.objects.filter(ambulatory_card_id=ambulatory_card_id).exclude(pk=instance.pk)
            else:
                existing = Patient.objects.filter(ambulatory_card_id=ambulatory_card_id)
            
            if existing.exists():
                raise ValidationError({
                    'ambulatory_card_id': 'Пацієнт з таким ID амбулаторної картки вже існує'
                })
        
        # Перевірка дат
        treatment_start = cleaned_data.get('treatment_start_date')
        discharge_date = cleaned_data.get('discharge_date')
        
        if treatment_start and discharge_date and discharge_date < treatment_start:
            raise ValidationError('Дата виписки не може бути раніше дати початку лікування')
        
        return cleaned_data

class FractionHistoryForm(forms.ModelForm):
    date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=True,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    class Meta:
        model = FractionHistory
        fields = '__all__'
        # widgets = {
        #     'date': forms.DateInput(attrs={'type': 'date'}),
        # }

class MedicalIncapacityForm(forms.ModelForm):
    start_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    end_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Форматуємо дати для відображення в полях
        date_fields = ['start_date', 'end_date']
        for field_name in date_fields:
            if self.instance.pk and getattr(self.instance, field_name):
                date_value = getattr(self.instance, field_name)
                if date_value:
                    self.initial[field_name] = date_value.strftime('%d.%m.%Y')
    
    class Meta:
        model = MedicalIncapacity
        exclude = ['patient']
        # widgets = {
        #     'start_date': forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'}),
        #     'end_date': forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'}),
        # }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if start_date and end_date and end_date < start_date:
            raise ValidationError('Дата закінчення не може бути раніше дати початку')
        
        return cleaned_data

class FractionEditForm(forms.ModelForm):
    """Форма для редагування фракції"""
    date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=True,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input', 'placeholder': 'дд.мм.рррр'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.date:
            self.initial['date'] = self.instance.date.strftime('%d.%m.%Y')
    
    class Meta:
        model = FractionHistory
        fields = ['date', 'dose', 'status', 'note', 'reason']
        widgets = {
            'dose': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'reason': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Причина зміни'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        return cleaned_data

class UserRegistrationForm(UserCreationForm):
    role = forms.ChoiceField(
        choices=[
            ('doctor', 'Лікар'),
            ('nurse', 'Медсестра'),
            ('admin', 'Адміністратор')
        ],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = User
        fields = ('username', 'password1', 'password2', 'role')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
        }

class UserLoginForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ім\'я користувача'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Пароль'})
    )


class TreatmentProtocolForm(forms.ModelForm):
    class Meta:
        from .models import TreatmentProtocol
        model = TreatmentProtocol
        fields = [
            'name', 'irradiation_zone', 'treatment_type',
            'total_fractions', 'dose_per_fraction_raw', 'has_radiomodification'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'напр. Молочна залоза (15 фр × 2.67 Гр)'}),
            'irradiation_zone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'напр. Молочна залоза'}),
            'treatment_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'напр. Ад\'ювантний'}),
            'total_fractions': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'напр. 15'}),
            'dose_per_fraction_raw': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'напр. 2.67 або 2.0/2.2'}),
            'has_radiomodification': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }