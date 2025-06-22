from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from datetime import timedelta

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
    last_name = models.CharField(max_length=255, blank=True, null=True)
    first_name = models.CharField(max_length=255, blank=True, null=True)
    middle_name = models.CharField(max_length=255, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=255, blank=True, null=True)
    diagnosis = models.CharField(max_length=255, blank=True, null=True)
    tnm_staging = models.CharField(max_length=255, blank=True, null=True)
    disease_stage = models.CharField(max_length=255, blank=True, null=True)
    clinical_group = models.CharField(max_length=255, blank=True, null=True)
    treatment_type = models.CharField(max_length=255, blank=True, null=True)
    treatment_phase = models.CharField(max_length=255, blank=True, null=True)
    histology_number = models.CharField(max_length=255, blank=True, null=True)
    histology_date = models.DateField(blank=True, null=True)
    histology_description = models.TextField(blank=True, null=True)
    ct_simulation_date = models.DateField(blank=True, null=True)
    treatment_start_date = models.DateField(blank=True, null=True)
    total_fractions = models.IntegerField(blank=True, null=True)
    stage_description = models.CharField(max_length=255, blank=True, null=True)
    current_fraction = models.IntegerField(blank=True, null=True)
    missed_days = models.IntegerField(blank=True, null=True)
    received_dose = models.FloatField(blank=True, null=True)
    inpatient_status = models.CharField(max_length=50, blank=True, null=True)
    ward_number = models.IntegerField(blank=True, null=True)
    prior_radiation = models.CharField(max_length=255, blank=True, null=True)
    discharge_date = models.DateField(blank=True, null=True)
    current_stage = models.CharField(max_length=255, blank=True, null=True)
    treatment_goal = models.CharField(max_length=255, blank=True, null=True)
    irradiation_zone = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    dose_per_fraction = models.FloatField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    last_blood_test_date = models.DateField(blank=True, null=True)

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

    def get_latest_medical_incapacity(self):
        return self.medical_incapacities.order_by('-end_date').first()

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
