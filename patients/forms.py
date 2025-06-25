from django import forms
from django.core.exceptions import ValidationError
from .models import Patient, FractionHistory, MedicalIncapacity, User
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import authenticate

class PatientForm(forms.ModelForm):
    birth_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'})
    )
    histology_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'})
    )
    ct_simulation_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'})
    )
    treatment_start_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'})
    )
    discharge_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'})
    )
    last_blood_test_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'})
    )
    class Meta:
        model = Patient
        fields = [
            'last_name', 'first_name', 'middle_name', 'birth_date', 'gender',
            'diagnosis', 'tnm_staging', 'disease_stage', 'clinical_group', 
            'treatment_type', 'histology_number', 'histology_date',
            'histology_description', 'ct_simulation_date', 'treatment_start_date',
            'total_fractions', 'dose_per_fraction', 'received_dose',
            'discharge_date', 'treatment_phase',
            'irradiation_zone', 'inpatient_status', 'ward_number', 'prior_radiation', 
            'last_blood_test_date', 'notes'
        ]
        widgets = {
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть прізвище'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть ім\'я'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Введіть по батькові'}),
            'gender': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('', 'Виберіть стать'),
                ('Ч', 'Чоловіча'),
                ('Ж', 'Жіноча')
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
            'treatment_start_date': forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'}),
            'total_fractions': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': 'Кількість фракцій'}),
            'dose_per_fraction': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': 0.1, 'placeholder': 'Доза на фракцію (Гр)'}),
            'received_dose': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': 0.1, 'placeholder': 'Отримана доза (Гр)'}),
            'missed_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': 'Пропущені дні'}),
            'current_stage': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('', 'Виберіть етап'),
                ('КТ-симуляція', 'КТ-симуляція'),
                ('початок лікування', 'Початок лікування'),
                ('лікування', 'Лікування'),
                ('виписка', 'Виписка')
            ]),
            'treatment_phase': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('', 'Виберіть фазу'),
                ('перша', 'Перша фаза'),
                ('друга', 'Друга фаза'),
                ('третя', 'Третя фаза')
            ]),
            'irradiation_zone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Зона опромінення'}),
            'inpatient_status': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('', 'Виберіть статус'),
                ('амбулаторно', 'Амбулаторно'),
                ('стаціонарно', 'Стаціонарно')
            ]),
            'ward_number': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Номер палати'}),
            'prior_radiation': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Попереднє опромінення'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Додаткові примітки'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        
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
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'})
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
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'})
    )
    end_date = forms.DateField(
        input_formats=['%d.%m.%Y', '%Y-%m-%d'],
        required=False,
        widget=forms.DateInput(attrs={'type': 'text', 'class': 'form-control datepicker-input'})
    )
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
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Логін'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Пароль'})
    ) 