import os
from django.core.management.base import BaseCommand
from django.core.files import File
from core.models import Person, FaceImage
from django.conf import settings

class Command(BaseCommand):
    help = 'Imports faces from the "photos" directory'

    def handle(self, *args, **options):
        # Path to the photos directory (relative to project root or absolute)
        # Assuming 'photos' is in the parent directory of the django project based on user structure
        photos_dir = os.path.abspath(os.path.join(settings.BASE_DIR, '..', 'photos'))
        
        if not os.path.exists(photos_dir):
            self.stdout.write(self.style.ERROR(f'Photos directory not found at: {photos_dir}'))
            return

        self.stdout.write(f'Scanning directory: {photos_dir}')

        count = 0
        for filename in os.listdir(photos_dir):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                name = os.path.splitext(filename)[0]
                file_path = os.path.join(photos_dir, filename)

                self.stdout.write(f'Processing {name}...')

                # Create or get Person
                person, created = Person.objects.get_or_create(name=name)
                
                # Check if this image is already imported (simple check by filename logic could be added, 
                # but here we just add it. To avoid duplicates, we could check if person has images)
                # For now, let's just add it.
                
                with open(file_path, 'rb') as f:
                    face_image = FaceImage(person=person)
                    face_image.image.save(filename, File(f), save=True)
                    count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Successfully imported {count} faces.'))
