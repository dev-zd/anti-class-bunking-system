from django.shortcuts import render, redirect, get_object_or_404
from django.http import StreamingHttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from .camera import VideoCamera
from .models import Person, FaceImage, Department
from django.core.files.base import ContentFile
import base64
import time
from django.utils import timezone
from datetime import timedelta
from django.db.models import Q
from .models import Attendance, MissingLog, PasswordResetOTP
import os
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import shutil
from django.conf import settings
import os
camera = None
CAMERA_ENABLED = False # Safety lock to prevent orphan requests from re-starting hardware

def get_camera(initialize=False):
    global camera, CAMERA_ENABLED
    if camera is None and initialize and CAMERA_ENABLED:
        print(" [!] Initializing VideoCamera singleton...")
        camera = VideoCamera()
    return camera

def release_camera():
    global camera
    if camera is not None:
        print(" [!] Releasing and destroying VideoCamera singleton...")
        camera.release()
        camera = None
        # Give the OS and driver a moment to truly clear the hardware lock
        import gc
        gc.collect()
        time.sleep(0.3)

def stop_camera(request):
    global CAMERA_ENABLED
    CAMERA_ENABLED = False
    release_camera()
    # Always redirect to scan without query params to prevent restart loop
    return redirect('scan')

@login_required
def dashboard_view(request):
    today = timezone.now().date()
    
    # Statistics
    total_students = Person.objects.count()
    present_today = Attendance.objects.filter(date=today).count()
    alerts_today = MissingLog.objects.filter(timestamp__date=today).count()
    missing_count = MissingLog.objects.filter(timestamp__date=today, status='Missing').count()
    found_count = MissingLog.objects.filter(timestamp__date=today, status='Found').count()
    
    # Recent Activity
    recent_logs = MissingLog.objects.all().order_by('-timestamp')[:5]
    
    # Chart Data (Last 7 Days)
    chart_days = []
    attendance_data = []
    alerts_data = []
    
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        chart_days.append(day.strftime('%b %d'))
        attendance_data.append(Attendance.objects.filter(date=day).count())
        alerts_data.append(MissingLog.objects.filter(timestamp__date=day).count())

    context = {
        'today': today,
        'total_students': total_students,
        'present_today': present_today,
        'alerts_today': alerts_today,
        'missing_count': missing_count,
        'found_count': found_count,
        'recent_logs': recent_logs,
        'chart_days': chart_days,
        'attendance_data': attendance_data,
        'alerts_data': alerts_data,
    }
    return render(request, 'core/dashboard.html', context)



def home(request):
    release_camera() # Ensure camera is off so browser can use it if needed later
    total_people = Person.objects.count()
    total_images = FaceImage.objects.count()
    context = {
        'total_people': total_people,
        'total_images': total_images,
    }
    return render(request, 'core/home.html', context)

from django.contrib import messages

@login_required
def register_view(request):
    # Force localhost for secure context (required for webcam access)
    if request.get_host().startswith('127.0.0.1'):
        from django.http import HttpResponsePermanentRedirect
        return HttpResponsePermanentRedirect(f'http://localhost:8000{request.path}')
    
    # SUPER aggressive camera release for registration
    global CAMERA_ENABLED, camera
    CAMERA_ENABLED = False
    if camera is not None:
        print(" [!] FORCE releasing camera for registration page...")
        camera.release()
        camera = None
        import gc
        gc.collect()
        time.sleep(0.5)  # Longer wait for Windows to fully release
    
    if request.method == 'POST':
        name = request.POST.get('name')
        class_name = request.POST.get('class_name')
        age = request.POST.get('age')
        department_id = request.POST.get('department')
        
        # Get multiple images
        files = request.FILES.getlist('image')
        
        if not name:
            messages.error(request, "Name is required.")
            return redirect('register')

        if len(files) < 5:
            messages.error(request, f"Please provide at least 5 photos. Received {len(files)}.")
            return redirect('register')

        # Get department instance
        department_obj = None
        if department_id:
            try:
                department_obj = Department.objects.get(id=department_id)
            except Department.DoesNotExist:
                messages.error(request, "Invalid department selected.")
                return redirect('register')

        # Create or get person
        person, created = Person.objects.get_or_create(
            name=name,
            defaults={
                'class_name': class_name,
                'age': age,
                'department': department_obj
            }
        )

        # Process uploaded files
        for f in files:
            face_img = FaceImage(person=person, image=f)
            face_img.save() # This generates encoding
            
        messages.success(request, f"Student {name} registered successfully with {len(files)} photos.")
        return redirect('register')
        
    departments = Department.objects.all()
    class_options = [c[0] for c in Person.CLASS_CHOICES]
    context = {
        'departments': departments,
        'class_options': class_options
    }
    return render(request, 'core/register.html', context)

def get_recognized_faces(request):
    global camera
    if camera:
        return JsonResponse({'faces': camera.current_recognized_faces})
    return JsonResponse({'faces': []})

def get_camera_status(request):
    global camera, CAMERA_ENABLED
    return JsonResponse({
        'backend_active': camera is not None,
        'camera_enabled_lock': CAMERA_ENABLED,
        'cam1_active': camera is not None and camera.cap1 is not None and camera.cap1.isOpened(),
        'cam2_active': camera is not None and camera.cap2 is not None and camera.cap2.isOpened()
    })

@login_required
def scan_view(request):
    global CAMERA_ENABLED
    # Check if the camera should be active (initial state is active)
    # We can use a query parameter to track "start" intent
    start_requested = request.GET.get('start', '0') == '1'
    if start_requested:
        CAMERA_ENABLED = True
    
    return render(request, 'core/scan.html', {'start_requested': start_requested})

def gen(camera):
    while True:
        if camera is None or camera.released:
            break
        frame = camera.get_frame()
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
        else:
            time.sleep(0.1) # Safe sleep to avoid CPU spinning if camera is unavailable

def video_feed(request):
    # Only the video feed is allowed to trigger camera startup
    return StreamingHttpResponse(gen(get_camera(initialize=True)),
                    content_type='multipart/x-mixed-replace; boundary=frame')

@login_required
def cctv_view(request):
    global CAMERA_ENABLED
    CAMERA_ENABLED = True
    return render(request, 'core/cctv.html')

def cctv_gen(camera):
    while True:
        if camera is None or camera.released:
            break
        frame = camera.get_cctv_frame()
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
        else:
            time.sleep(0.1)

def cctv_feed(request):
    return StreamingHttpResponse(cctv_gen(get_camera(initialize=True)),
                    content_type='multipart/x-mixed-replace; boundary=frame')

@login_required
def gallery_view(request):
    release_camera()
    people = Person.objects.all().order_by('-created_at').prefetch_related('images')
    return render(request, 'core/gallery.html', {'people': people})

@login_required
def delete_person(request, person_id):
    if request.method == 'POST':
        try:
            person = Person.objects.get(id=person_id)
            
            # Path to person's folder
            folder_path = os.path.join(settings.MEDIA_ROOT, 'faces', person.name)
            
            # Delete database record (CASCADE handles FaceImage records)
            person.delete()
            
            # Delete the folder from filesystem if it exists
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
                
            messages.success(request, f'Student {person.name} and all their data deleted.')
        except Person.DoesNotExist:
            pass
    return redirect('gallery')

@login_required
def delete_face(request, face_id):
    if request.method == 'POST':
        try:
            face = FaceImage.objects.get(id=face_id)
            person_id = face.person.id
            # Delete the file from filesystem
            if face.image:
                face.image.delete(save=False)
            # Delete the database record
            face.delete()
            
            # Smart redirect
            referer = request.META.get('HTTP_REFERER')
            if referer and 'edit_person' in referer:
                return redirect('edit_person', person_id=person_id)
        except FaceImage.DoesNotExist:
            pass
    return redirect('gallery')

@login_required
def edit_face(request, face_id):
    try:
        face = FaceImage.objects.get(id=face_id)
        person = face.person
    except FaceImage.DoesNotExist:
        return redirect('gallery')

    if request.method == 'POST':
        name = request.POST.get('name')
        class_name = request.POST.get('class_name')
        age = request.POST.get('age')
        department_id = request.POST.get('department')
        image_data = request.POST.get('image_data')
        image_file = request.FILES.get('image')

        if name:
            person.name = name
            person.class_name = class_name
            person.age = age if age else None
            
            if department_id:
                 try:
                    person.department = Department.objects.get(id=department_id)
                 except Department.DoesNotExist:
                    pass # Or handle error
            else:
                person.department = None

            person.save()

            if image_data or image_file:
                if image_data:
                    # Handle Base64 captured image
                    format, imgstr = image_data.split(';base64,') 
                    ext = format.split('/')[-1] 
                    data = ContentFile(base64.b64decode(imgstr), name=f'{name}_capture.{ext}')
                    if face.image:
                        face.image.delete(save=False)
                    face.image = data
                else:
                    if face.image:
                        face.image.delete(save=False)
                    face.image = image_file
                
                face.encoding = None # Force re-encoding
                face.save()
            
            return redirect('gallery')

    departments = Department.objects.all()
    class_options = [c[0] for c in Person.CLASS_CHOICES]
    return render(request, 'core/edit_face.html', {'face': face, 'person': person, 'departments': departments, 'class_options': class_options})

@login_required
def edit_person(request, person_id):
    person = get_object_or_404(Person, id=person_id)
    if request.method == 'POST':
        name = request.POST.get('name')
        class_name = request.POST.get('class_name')
        age = request.POST.get('age')
        department_id = request.POST.get('department')
        files = request.FILES.getlist('image')
        
        if name:
            person.name = name
            person.class_name = class_name
            person.age = age if age else None
            
            if department_id:
                try:
                    person.department = Department.objects.get(id=department_id)
                except Department.DoesNotExist:
                    person.department = None
            else:
                person.department = None
            
            person.save()
            
            # Process new uploaded files
            if files:
                for f in files:
                    face_img = FaceImage(person=person, image=f)
                    face_img.save()
            
            messages.success(request, f"Student {name} updated successfully.")
            return redirect('gallery')
            
    departments = Department.objects.all()
    class_options = [c[0] for c in Person.CLASS_CHOICES]
    return render(request, 'core/edit_person.html', {
        'person': person, 
        'departments': departments, 
        'class_options': class_options
    })

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'core/login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        
        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
        else:
            user = User.objects.create_user(username=username, email=email, password=password1)
            messages.success(request, 'Account created successfully. Please log in.')
            return redirect('login')
            
    return render(request, 'core/signup.html')

def send_otp_email(user, otp):
    # Reuse credentials from camera.py or common config
    # For now, hardcoding based on camera.py as requested
    EMAIL_SENDER = "victusho182@gmail.com"
    EMAIL_PASSWORD = "lajd qmor mgrk oztt"
    
    subject = "FaceRec Pro - Password Reset OTP"
    body = f"Hello {user.username},\n\nYour OTP for password reset is: {otp}\n\nThis OTP is valid for 10 minutes.\n\nIf you did not request this, please ignore this email."
    
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = user.email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, user.email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending OTP: {e}")
        return False

def forgot_password_view(request):
    if request.method == 'POST':
        identifier = request.POST.get('user_identifier')
        user = User.objects.filter(Q(username=identifier) | Q(email=identifier)).first()
        
        if user:
            if not user.email:
                messages.error(request, "This user does not have an email address associated.")
                return redirect('forgot_password')
                
            otp = str(random.randint(100000, 999999))
            # Delete old OTPs for this user
            PasswordResetOTP.objects.filter(user=user).delete()
            PasswordResetOTP.objects.create(user=user, otp=otp)
            
            if send_otp_email(user, otp):
                request.session['reset_user_id'] = user.id
                messages.success(request, f"OTP has been sent to {user.email}")
                return redirect('verify_otp')
            else:
                messages.error(request, "Failed to send email. Please try again later.")
        else:
            messages.error(request, "User not found.")
            
    return render(request, 'core/forgot_password.html')

def verify_otp_view(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return redirect('forgot_password')
        
    if request.method == 'POST':
        otp_entered = request.POST.get('otp')
        otp_obj = PasswordResetOTP.objects.filter(user_id=user_id, otp=otp_entered).first()
        
        if otp_obj:
            if otp_obj.is_expired():
                messages.error(request, "OTP has expired. Please request a new one.")
                return redirect('forgot_password')
            
            request.session['otp_verified'] = True
            return redirect('reset_password')
        else:
            messages.error(request, "Invalid OTP.")
            
    return render(request, 'core/verify_otp.html')

def reset_password_view(request):
    user_id = request.session.get('reset_user_id')
    otp_verified = request.session.get('otp_verified')
    
    if not user_id or not otp_verified:
        return redirect('forgot_password')
        
    if request.method == 'POST':
        pass1 = request.POST.get('pass1')
        pass2 = request.POST.get('pass2')
        
        if pass1 != pass2:
            messages.error(request, "Passwords do not match.")
        else:
            user = User.objects.get(id=user_id)
            user.set_password(pass1)
            user.save()
            # Clean up
            PasswordResetOTP.objects.filter(user=user).delete()
            del request.session['reset_user_id']
            del request.session['otp_verified']
            
            messages.success(request, "Password reset successful. Please log in.")
            return redirect('login')
            
    return render(request, 'core/reset_password.html')

from django.db.models import Q
from .models import Attendance, MissingLog
import datetime

@login_required
def report_view(request):
    logs = MissingLog.objects.all().order_by('-timestamp')
    return render(request, 'core/report.html', {'logs': logs})

@login_required
def delete_log(request, log_id):
    if request.method == "POST":
        log = get_object_or_404(MissingLog, id=log_id)
        log.delete()
        messages.success(request, "Log entry deleted successfully.")
    return redirect('report')

@login_required
def daily_report_view(request, date_str):
    try:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)

    # Get all people
    all_people = Person.objects.all().order_by('name')
    
    # Get attendance for the day
    attendance_records = Attendance.objects.filter(date=date_obj).select_related('person')
    present_ids = set(attendance_records.values_list('person_id', flat=True))
    
    # Categorize
    present_list = []
    absent_list = []
    
    # Map attendance times
    attendance_map = {a.person_id: a.time_in for a in attendance_records}

    for person in all_people:
        if person.id in present_ids:
            present_list.append({
                'name': person.name,
                'class_name': person.class_name,
                'department': person.department,
                'time_in': attendance_map[person.id].strftime('%H:%M:%S')
            })
        else:
            absent_list.append({
                'name': person.name,
                'class_name': person.class_name,
                'department': person.department
            })
            
    return JsonResponse({
        'date': date_str,
        'present': present_list,
        'absent': absent_list
    })
