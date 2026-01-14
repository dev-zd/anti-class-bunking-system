from django.db import models
import face_recognition
import numpy as np
import pickle
import os

def get_face_image_path(instance, filename):
    # Store images in faces/<person_name>/<filename>
    return os.path.join('faces', instance.person.name, filename)

class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Person(models.Model):
    name = models.CharField(max_length=100)
    
    CLASS_CHOICES = [
        ('S1', 'S1'),
        ('S2', 'S2'),
        ('S3', 'S3'),
        ('S4', 'S4'),
        ('S5', 'S5'),
        ('S6', 'S6'),
    ]
    class_name = models.CharField(max_length=50, blank=True, choices=CLASS_CHOICES)
    age = models.IntegerField(null=True, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class FaceImage(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=get_face_image_path)
    encoding = models.BinaryField(null=True, blank=True) # Store numpy array as bytes

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.encoding:
            self.generate_encoding()

    def generate_encoding(self):
        try:
            # Load image using face_recognition
            image = face_recognition.load_image_file(self.image.path)
            encodings = face_recognition.face_encodings(image)
            if encodings:
                # Store the first encoding found
                self.encoding = pickle.dumps(encodings[0])
                self.save(update_fields=['encoding'])
        except Exception as e:
            print(f"Error generating encoding for {self.image.path}: {e}")

class Attendance(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField(auto_now_add=True)
    time_in = models.TimeField(auto_now_add=True)

    class Meta:
        unique_together = ('person', 'date')

    def __str__(self):
        return f"{self.person.name} - {self.date}"

from django.utils import timezone

class MissingLog(models.Model):
    name = models.CharField(max_length=100)
    timestamp = models.DateTimeField(default=timezone.now)
    location = models.CharField(max_length=50, default='Classroom')
    status = models.CharField(max_length=50, default='Missing') # Missing, Found

    def __str__(self):
        return f"{self.name} - {self.status} in {self.location} at {self.timestamp}"
