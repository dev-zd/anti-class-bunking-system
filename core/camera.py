import cv2
import face_recognition
import numpy as np
import pickle
import os
import time
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from ultralytics import YOLO
from django.utils import timezone
from .models import FaceImage, Attendance, Person, MissingLog

# ---------------- CONFIG ----------------
EMAIL_SENDER = "victusho182@gmail.com"
EMAIL_PASSWORD = "lajd qmor mgrk oztt"
EMAIL_RECEIVER = "devkrishnayou@gmail.com"

# YOLO Model Path
YOLO_MODEL_PATH = "yolo11n-face.pt"
CONFIDENCE_THRESHOLD = 0.5
TOLERANCE = 0.65
PROCESS_EVERY_N_FRAMES = 90  # Increased from 60 to reduce stuttering
SCALE_FACTOR = 0.35
MISSING_THRESHOLD = 15.0 # seconds
TARGET_STUDENT = "Dev"
JPEG_QUALITY = 75  # Reduce quality for faster encoding
RETRY_INTERVAL = 450 # Increased significantly (~15s) to prevent flickering/phantom feeds

class VideoCamera(object):
    def __init__(self):
        # Initialize Cameras
        print("Initializing cameras...")
        self.cap1 = self.open_stream(0)
        self.cap2 = self.open_stream(1) # Re-enable cam 2
        
        self.known_face_encodings = []
        self.known_face_names = []
        self.known_face_details = {}
        self.attendance_marked = set()
        self.analysis_resources_loaded = False # Deferred loading flag
        
        # State tracking
        self.frame_count = 0
        self.last_data1 = {"face_locations": [], "face_names": []}
        self.last_data2 = {"face_locations": [], "face_names": []}
        
        self.last_seen_time = None # Initialize as None to wait for first detection
        self.email_sent = False
        self.last_retry_frame = 0
        self.target_detected_once = False # Track if student was ever seen
        
        # For web display
        self.current_recognized_faces = []

        self.released = False # Add flag to prevent auto-restart after release

    def ensure_analysis_resources(self):
        """Loads heavy resources (YOLO, Database) only when needed."""
        if self.analysis_resources_loaded:
            return
            
        print(" [!] Loading Analysis Resources (YOLO + Face Database)...")
        
        # Load YOLO Model
        try:
            self.model = YOLO(YOLO_MODEL_PATH)
        except Exception as e:
            print(f"Error loading YOLO model: {e}")
            self.model = None

        self.load_known_faces()
        
        # Pre-load today's attendance to avoid duplicate attempts on restart
        today = timezone.now().date()
        present_ids = Attendance.objects.filter(date=today).values_list('person_id', flat=True)
        self.attendance_marked = set(present_ids)
        print(f" [i] Loaded {len(self.attendance_marked)} attendance records for today.")
        
        self.analysis_resources_loaded = True

    def open_stream(self, src, ref_cap=None):
        # Strictly enforce DSHOW on Windows for stability
        backend = cv2.CAP_DSHOW if os.name == 'nt' else None
        backend_name = "DSHOW" if backend else "Default"
        
        print(f" [?] Attempting to open Camera {src} using {backend_name}...")
        
        try:
            if backend is not None:
                cap = cv2.VideoCapture(src, backend)
            else:
                cap = cv2.VideoCapture(src)
            
            if not cap.isOpened():
                print(f" [X] Camera {src} failed to open (isOpened is False). Device might be in use.")
                return None
                
            # Performance optimizations
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Critical Read Test
            print(f" [?] Testing physical read for Camera {src}...")
            ret, frame = cap.read()
            if ret and frame is not None:
                # PHANTOM MIRROR PREVENTION: Check if this is just a duplicate of another camera
                if ref_cap and ref_cap.isOpened():
                    ret_ref, frame_ref = ref_cap.read()
                    if ret_ref and frame_ref is not None:
                        # Compare resized frames for speed and to avoid tiny noise differences
                        f1 = cv2.resize(frame, (160, 120))
                        f2 = cv2.resize(frame_ref, (160, 120))
                        diff = cv2.absdiff(f1, f2)
                        mean_diff = np.mean(diff)
                        
                        # If mean difference is extremely low, it's a mirror/phantom
                        if mean_diff < 5.0: # Threshold for identical feed
                            print(f" [!] Camera {src} appears to be a MIRROR of Camera 0. Rejecting.")
                            cap.release()
                            return None

                print(f" [V] Camera {src} is STREAMING (Shape: {frame.shape}).")
                return cap
            else:
                print(f" [X] Camera {src} opened but failed to read frame. Check permissions or cable.")
                cap.release()
        except Exception as e:
            print(f" [!] EXCEPTION during Camera {src} init: {e}")
            
        return None

    def __del__(self):
        self.release()

    def release(self):
        self.released = True # Block any further reads or auto-retries
        if hasattr(self, 'cap1') and self.cap1 and self.cap1.isOpened():
            self.cap1.release()
            self.cap1 = None
        if hasattr(self, 'cap2') and self.cap2 and self.cap2.isOpened():
            self.cap2.release()
            self.cap2 = None

    def load_known_faces(self):
        """Loads face encodings from the database."""
        self.known_face_encodings = []
        self.known_face_names = []
        self.known_face_details = {} 
        
        faces = FaceImage.objects.exclude(encoding=None).select_related('person', 'person__department')
        for face in faces:
            if face.encoding:
                try:
                    encoding = pickle.loads(face.encoding)
                    self.known_face_encodings.append(encoding)
                    name = face.person.name
                    self.known_face_names.append(name)
                    
                    # Robust lookup for department
                    dept_name = "None"
                    try:
                        if face.person.department:
                            dept_name = face.person.department.name
                    except Exception: pass

                    self.known_face_details[name] = {
                        'name': name,
                        'id': face.person.id, 
                        'class_name': face.person.class_name,
                        'age': face.person.age,
                        'department': dept_name,
                        'time': timezone.now().strftime("%H:%M") 
                    }
                except Exception as e:
                    print(f"Error loading encoding for {face.person.name}: {e}")
                    
        print(f"Loaded {len(self.known_face_encodings)} known faces.")

    def send_alert_email(self, student_name, missing_duration):
        if "your_email" in EMAIL_SENDER: return
        subject = f"ALERT: {student_name} is Missing!"
        
        # Capture exact time for synchronization
        now = timezone.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        body = (f"URGENT: {student_name} has not been seen for {int(missing_duration)} seconds.\n\n"
                f"Time of Alert: {timestamp_str}")
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
            server.quit()
            
            # Log the event
            try:
                # Passing the captured 'now' object to ensure sync
                MissingLog.objects.create(name=student_name, timestamp=now, location='Classroom', status='Missing')
                print(f" [!] Logged Missing Event for {student_name} at {timestamp_str}")
            except Exception as e:
                print(f"Failed to save Missing Log: {e}")

        except: pass

    def send_corridor_email(self, student_name, found_time):
        if "your_email" in EMAIL_SENDER: return
        subject = f"ALERT: {student_name} FOUND in Corridor!"
        
        timestamp_str = found_time.strftime("%Y-%m-%d %H:%M:%S")
        
        body = (f"UPDATE: {student_name} was found in the Corridor at {timestamp_str}.\n"
                f"Please verify their status.")
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
            server.quit()
            
            # Log the event
            try:
                MissingLog.objects.create(
                    name=student_name, 
                    timestamp=found_time,
                    location='Corridor',
                    status='Found'
                )
                print(f" [!] Logged Corridor Event for {student_name} at {timestamp_str}")
            except Exception as e:
                print(f"Failed to save Corridor Log: {e}")
        except: pass

    def process_stream_logic(self, frame, last_data):
        if frame is None: return None, [], last_data
        display_frame = frame.copy()
        current_face_locations = last_data["face_locations"]
        current_face_names = last_data["face_names"]
        
        if self.frame_count % PROCESS_EVERY_N_FRAMES == 0 and self.model:
            small_frame = cv2.resize(frame, (0, 0), fx=SCALE_FACTOR, fy=SCALE_FACTOR)
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            results = self.model(small_frame, verbose=False, conf=CONFIDENCE_THRESHOLD)
            face_locations = []
            for box in results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                face_locations.append((int(y1), int(x2), int(y2), int(x1)))
            
            face_encodings = []
            try:
                face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)
            except: pass
                
            face_names = []
            for enc in face_encodings:
                if not self.known_face_encodings:
                    face_names.append("Unknown")
                    continue
                distances = face_recognition.face_distance(self.known_face_encodings, enc)
                best_idx = np.argmin(distances)
                name = self.known_face_names[best_idx] if distances[best_idx] < TOLERANCE else "Unknown"
                face_names.append(name)
            current_face_locations, current_face_names = face_locations, face_names
            
        last_data["face_locations"], last_data["face_names"] = current_face_locations, current_face_names
        scale_up = 1.0 / SCALE_FACTOR
        for (t, r, b, l), name in zip(current_face_locations, current_face_names):
            top, right, bottom, left = int(t * scale_up), int(r * scale_up), int(b * scale_up), int(l * scale_up)
            color = (0, 200, 0) if name != "Unknown" else (0, 0, 255)
            cv2.rectangle(display_frame, (left, top), (right, bottom), color, 1)
            cv2.rectangle(display_frame, (left, bottom - 20), (right, bottom), color, cv2.FILLED)
            cv2.putText(display_frame, name, (left + 4, bottom - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return display_frame, current_face_names, last_data

    def get_cctv_frame(self):
        if self.released:
            return None

        # Similar retry logic as get_frame
        if self.frame_count - self.last_retry_frame > RETRY_INTERVAL:
            self.last_retry_frame = self.frame_count
            if not self.cap1 or not self.cap1.isOpened(): 
                print(" [!] Cooldown over - Attempting to recover Camera 1...")
                self.cap1 = self.open_stream(0)
            if not self.cap2 or not self.cap2.isOpened(): 
                print(" [!] Cooldown over - Attempting to recover Camera 2...")
                # Pass cap1 as reference to detect mirroring
                self.cap2 = self.open_stream(1, ref_cap=self.cap1)
        
        ret1, frame1 = self.cap1.read() if (self.cap1 and self.cap1.isOpened()) else (False, None)
        ret2, frame2 = self.cap2.read() if (self.cap2 and self.cap2.isOpened()) else (False, None)
        self.frame_count += 1

        # Process frame 1
        if ret1 and frame1 is not None and frame1.size > 0:
            # Fix blue tint (OpenCV captures in BGR, we need RGB for web display)
            disp1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2RGB)
        else:
            disp1 = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(disp1, "cam1 not available at the moment", (50, 240), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            if self.cap1: 
                self.cap1.release()
                self.cap1 = None

        # Process frame 2
        if ret2 and frame2 is not None and frame2.size > 0:
            # Fix blue tint
            disp2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2RGB)
        else:
            disp2 = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(disp2, "cam2 not available at the moment", (50, 240), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            if self.cap2:
                self.cap2.release()
                self.cap2 = None

        # Merge frames horizontally
        combined_display = np.hstack((disp1, disp2))

        # Convert back to BGR for JPEG encoding (imencode expects BGR)
        combined_display_bgr = cv2.cvtColor(combined_display, cv2.COLOR_RGB2BGR)

        # Encode to JPEG
        ret, jpeg = cv2.imencode('.jpg', combined_display_bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        return jpeg.tobytes() if ret else None

    def get_frame(self):
        if self.released:
            return None

        # Ensure heavy resources are loaded for analysis
        self.ensure_analysis_resources()

        # Auto-retry Logic (only if not explicitly released)
        if self.frame_count - self.last_retry_frame > RETRY_INTERVAL:
            self.last_retry_frame = self.frame_count
            if not self.cap1 or not self.cap1.isOpened(): 
                self.cap1 = self.open_stream(0)
            if not self.cap2 or not self.cap2.isOpened(): 
                self.cap2 = self.open_stream(1, ref_cap=self.cap1)
        
        ret1, frame1 = self.cap1.read() if (self.cap1 and self.cap1.isOpened()) else (False, None)
        ret2, frame2 = self.cap2.read() if (self.cap2 and self.cap2.isOpened()) else (False, None)
        self.frame_count += 1
        
        # Process active streams
        disp1, names1 = None, []
        if ret1:
            disp1, names1, self.last_data1 = self.process_stream_logic(frame1, self.last_data1)
        else:
            disp1 = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(disp1, "CAM 1 LOST", (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            
        disp2, names2 = None, []
        if ret2:
            disp2, names2, self.last_data2 = self.process_stream_logic(frame2, self.last_data2)
        elif self.cap2: # Only show "LOST" if we actually have/expect a second camera
            disp2 = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(disp2, "CAM 2 LOST", (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        
        # Merge frames
        # Merge frames
        if disp2 is not None:
             combined_display = np.hstack((disp1, disp2))
        else:
             combined_display = disp1

        # LOGIC SEPARATION
        # names1 = Classroom (Attendance, Missing Check)
        # names2 = Corridor (Safe Zone, Found Check)
        
        all_names = names1 + names2 # Only for display stats if needed

        # Web API Updates
        # Web API Updates & Attendance (CLASSROOM ONLY - names1)
        self.current_recognized_faces = []
        seen = set()
        
        # Only mark attendance from Classroom Camera
        for n in names1:
            if n != "Unknown" and n not in seen and n in self.known_face_details:
                self.current_recognized_faces.append(self.known_face_details[n])
                # Mark Attendance
                try:
                    person_data = self.known_face_details[n]
                    p_id = person_data.get('id')
                    
                    if p_id and p_id not in self.attendance_marked:
                        print(f" [!] Marking attendance for {n} (ID: {p_id})")
                        # Create record
                        Attendance.objects.create(person_id=p_id)
                        # Add to local cache to prevent re-hits
                        self.attendance_marked.add(p_id)
                except Exception as e:
                    # Ignore uniqueness errors (race conditions) or other passing errors
                    # print(f"Attendance error: {e}")
                    pass

        # Stats & Alerts
        u_known = set(n for n in all_names if n != "Unknown") # Shared stats
        k_count, t_count = len(u_known), len(u_known) + all_names.count("Unknown")
        
        # CHECK MISSING STATUS (CLASSROOM ONLY - names1)
        target_found_in_class = any(n.strip().lower() == TARGET_STUDENT.strip().lower() for n in names1)
        
        if target_found_in_class:
            if self.email_sent:
                 # Log that the person is found again in class
                 try:
                     MissingLog.objects.create(
                         name=TARGET_STUDENT,
                         timestamp=timezone.now(),
                         status='the person found again in class',
                         location='Classroom'
                     )
                     print(f" [!] Logged Return for {TARGET_STUDENT}")
                 except Exception as e:
                     print(f"Failed to log return: {e}")
            
            self.last_seen_time = time.time()
            self.email_sent = False
            self.target_detected_once = True 
        
        elapsed = (time.time() - self.last_seen_time) if self.last_seen_time else 0.0
        
        cv2.rectangle(combined_display, (10, 10), (220, 110), (0, 0, 0), cv2.FILLED)
        cv2.putText(combined_display, f"Total: {t_count}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
        cv2.putText(combined_display, f"Known: {k_count}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
        
        # Only show and count missing if they have been seen at least once
        if self.target_detected_once:
            color = (0, 255, 255) if elapsed < MISSING_THRESHOLD else (0, 0, 255)
            cv2.putText(combined_display, f"Missing: {elapsed:.1f}s", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
            if elapsed > MISSING_THRESHOLD:
                # Check if found in Corridor (Camera 2)
                target_in_corridor = any(n.strip().lower() == TARGET_STUDENT.strip().lower() for n in names2)
                
                if target_in_corridor and self.email_sent: # If already marked missing, but now found
                     # Reset missing logic? Or just log "Found"?
                     # For now, let's just log "Found" once if we haven't already
                     # We need a state to track provided they were missing
                     if not getattr(self, 'corridor_alert_sent', False):
                         print(f" [!] TARGET FOUND IN CORRIDOR!")
                         self.send_corridor_email(TARGET_STUDENT, timezone.now())
                         self.corridor_alert_sent = True

                h, w = combined_display.shape[:2]
                cv2.rectangle(combined_display, (w//2-200, h//2-40), (w//2+200, h//2+40), (0, 0, 255), cv2.FILLED)
                cv2.putText(combined_display, "ALERT: Dev Missing", (w//2-180, h//2+10), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 3)
                
                if not self.email_sent: 
                    self.send_alert_email(TARGET_STUDENT, elapsed)
                    self.email_sent = True
                    self.corridor_alert_sent = False # Reset corridor alert for this new missing event
        else:
            cv2.putText(combined_display, "Waiting for local target...", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        # Use lower quality JPEG for faster encoding and smoother streaming
        ret, jpeg = cv2.imencode('.jpg', combined_display, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        return jpeg.tobytes() if ret else None
