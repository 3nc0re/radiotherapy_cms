from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from datetime import date, timedelta

class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('The Username must be set')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('approved', True)
        extra_fields.setdefault('role', 'admin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
            
        return self.create_user(username, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(unique=True, max_length=255)
    password = models.CharField(max_length=255)
    role = models.CharField(max_length=255)
    doctor = models.ForeignKey('self', models.DO_NOTHING, blank=True, null=True, db_column='doctor_id')
    approved = models.BooleanField()
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    # These fields were added by the script
    last_login = models.DateTimeField(blank=True, null=True)
    is_superuser = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    # To avoid clashes with default User model's relations
    groups = models.ManyToManyField(
        'auth.Group', blank=True, related_name="custom_user_groups", related_query_name="user"
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission', blank=True, related_name="custom_user_permissions", related_query_name="user"
    )

    objects = UserManager()
    USERNAME_FIELD = 'username'
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    
    def get_role_display(self):
        return self.role.capitalize()

    class Meta:
        db_table = 'users'

class Patient(models.Model):
    # Особиста інформація
    last_name = models.CharField(max_length=255, blank=True, null=True, help_text="Прізвище")
    first_name = models.CharField(max_length=255, blank=True, null=True, help_text="Ім'я")
    middle_name = models.CharField(max_length=255, blank=True, null=True, help_text="По батькові")
    birth_date = models.DateField(blank=True, null=True, help_text="Дата народження")
    gender = models.CharField(max_length=10, blank=True, null=True, choices=[('Ч', 'Чоловіча'), ('Ж', 'Жіноча')], help_text="Стать")
    
    # Діагноз та стадіювання
    diagnosis = models.CharField(max_length=255, blank=True, null=True, help_text="Діагноз")
    tnm_staging = models.CharField(max_length=255, blank=True, null=True, help_text="Стадіювання за TNM")
    disease_stage = models.CharField(max_length=255, blank=True, null=True, help_text="Стадія захворювання (текст)")
    clinical_group = models.CharField(max_length=255, blank=True, null=True, help_text="Клінічна група (текст)")

    # Інформація про лікування
    treatment_type = models.CharField(max_length=255, blank=True, null=True, help_text="Тип лікування")
    treatment_phase = models.CharField(max_length=255, blank=True, null=True, help_text="Фаза лікування")
    irradiation_zone = models.CharField(max_length=255, blank=True, null=True, help_text="Зона опромінення")
    total_fractions = models.IntegerField(blank=True, null=True, help_text="Загальна кількість фракцій")
    dose_per_fraction = models.FloatField(blank=True, null=True, help_text="РОД (Гр)")
    received_dose = models.FloatField(blank=True, null=True, help_text="СОД (Гр)")

    # Дати
    ct_simulation_date = models.DateField(blank=True, null=True, help_text="Дата КТ-симуляції")
    treatment_start_date = models.DateField(blank=True, null=True, help_text="Дата початку лікування")
    discharge_date = models.DateField(blank=True, null=True, help_text="Дата виписки")
    last_blood_test_date = models.DateField(blank=True, null=True, help_text="Дата останнього аналізу крові")

    # Гістологія
    histology_number = models.CharField(max_length=255, blank=True, null=True, help_text="Номер гістології")
    histology_date = models.DateField(blank=True, null=True, help_text="Дата гістології")
    histology_description = models.TextField(blank=True, null=True, help_text="Опис гістології")
    
    # Стаціонар та інше
    inpatient_status = models.CharField(max_length=50, blank=True, null=True, help_text="Статус госпіталізації")
    ward_number = models.IntegerField(blank=True, null=True, help_text="Номер палати")
    prior_radiation = models.CharField(max_length=255, blank=True, null=True, help_text="Попереднє опромінення")
    notes = models.TextField(blank=True, null=True, help_text="Примітки")
    
    # Системні
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)

    @property
    def full_name(self):
        return f"{self.last_name} {self.first_name} {self.middle_name}".strip()

    @property
    def display_stage(self):
        """
        Динамічно визначає поточний етап пацієнта на основі дат.
        """
        today = timezone.now().date()
        
        if self.discharge_date and self.discharge_date <= today:
            return "Архів"
        
        three_days_later = today + timedelta(days=3)
        if self.discharge_date and today < self.discharge_date <= three_days_later:
            return "Підготовка до виписки"
        
        if self.treatment_start_date and self.treatment_start_date <= today:
            return "Лікування"
            
        if self.ct_simulation_date and not self.treatment_start_date:
            return "КТ-симуляція"

        if self.treatment_start_date and self.treatment_start_date > today:
            return "Початок лікування"

        return "Новий"

    @property
    def current_fraction(self):
        """Динамічно розраховує кількість проведених фракцій."""
        return self.fractions.filter(delivered=True).count()

    @property
    def missed_days(self):
        """Динамічно розраховує кількість пропущених робочих днів лікування."""
        if not self.treatment_start_date or not self.is_in_treatment:
            return 0
        
        today = date.today()
        end_date = self.discharge_date if self.discharge_date and self.discharge_date < today else today
        
        # Розраховуємо загальну кількість робочих днів з початку лікування
        total_weekdays = 0
        current_date = self.treatment_start_date
        while current_date <= end_date:
            if current_date.weekday() < 5: # 0-4 corresponds to Mon-Fri
                total_weekdays += 1
            current_date += timedelta(days=1)
            
        # Кількість пропущених днів = очікувані фракції - фактичні фракції
        delivered_fractions = self.fractions.filter(delivered=True).count()
        missed = total_weekdays - delivered_fractions
        return max(0, missed)

    @property
    def next_blood_test_due_date(self):
        """Розраховує наступну рекомендовану дату аналізу крові (через 10 днів, тільки будні)."""
        if not self.last_blood_test_date or not self.is_in_treatment:
            return None
            
        target_date = self.last_blood_test_date + timedelta(days=10)
        
        # Якщо дата випадає на вихідний, переносимо на найближчий понеділок
        if target_date.weekday() >= 5: # Saturday or Sunday
            target_date += timedelta(days=7 - target_date.weekday())
            
        return target_date

    @property
    def is_in_treatment(self):
        """Перевіряє, чи пацієнт наразі проходить лікування."""
        today = date.today()
        if self.treatment_start_date and self.treatment_start_date <= today:
            if not self.discharge_date or self.discharge_date >= today:
                return True
        return False

    def get_latest_medical_incapacity(self):
        return self.medical_incapacities.order_by('-end_date').first()

    def get_diagnosis_text_for_copy(self):
        """Формує текст діагнозу для копіювання в інші системи"""
        parts = []
        
        # Основний діагноз
        if self.diagnosis:
            parts.append(self.diagnosis)
        
        # TNM стадіювання
        if self.tnm_staging:
            parts.append(self.tnm_staging)
        
        # Стадія захворювання
        if self.disease_stage:
            parts.append(f"gr. {self.disease_stage}")
        
        # Клінічна група
        if self.clinical_group:
            parts.append(f"кл. гр. {self.clinical_group}")
        
        # Стан після лікування
        if self.treatment_type:
            if self.treatment_type == 'радикальне':
                parts.append("Стан після радикального лікування")
            elif self.treatment_type == 'паліативне':
                parts.append("Стан після паліативного лікування")
            elif self.treatment_type == 'симптоматичне':
                parts.append("Стан після симптоматичного лікування")
        
        # Гістологія
        if self.histology_number and self.histology_date:
            hist_date = self.histology_date.strftime('%d.%m.%Y')
            parts.append(f"ПГЗ № {self.histology_number} від {hist_date}")
        
        # Опис гістології
        if self.histology_description:
            parts.append(f"- {self.histology_description}")
        
        return ". ".join(parts) if parts else "Діагноз не вказано"

    def __str__(self):
        return self.full_name

    class Meta:
        db_table = 'patients'

class FractionHistory(models.Model):
    patient = models.ForeignKey('Patient', models.DO_NOTHING, related_name='fractions')
    date = models.DateField()
    dose = models.FloatField()
    delivered = models.BooleanField(blank=True, null=True)
    confirmed_by_doctor = models.BooleanField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'fraction_history'

class MedicalIncapacity(models.Model):
    patient = models.ForeignKey('Patient', models.DO_NOTHING, related_name='medical_incapacities')
    mvt_number = models.CharField(max_length=19, blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    no_employment_relation = models.BooleanField(blank=True, null=True)
    no_employment_relation_text = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = 'medical_incapacity'
