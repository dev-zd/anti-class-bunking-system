# Anti-Class Bunking System 🛡️

A premium, real-time surveillance and attendance management system powered by Face Recognition and AI. Designed to monitor student presence across multiple locations (Classroom & Corridors) and alert authorities in case of unauthorized absence. (!!This is a completely a prototype model which uses 2 camera's which are laptop 'default camera' and an external webcamera to act as second camera!!)

![Dashboard Preview](https://via.placeholder.com/800x400?text=Anti-Class+Bunking+System+Dashboard)

## 🚀 Key Features

### 🔍 Smart Detection & Recognition
- **Face Recognition**: Real-time identification using `face_recognition` and `OpenCV`.
- **AI-Powered Detection**: High-speed face localization using **YOLOv11**.
- **Dual Camera Support**: Simultaneous monitoring of two zones (e.g., Camera 1 for Classroom, Camera 2 for Corridors).

### 🚨 Real-time Alerts
- **Missing Person Detection**: Automatically detects if a target student leaves the classroom and enters the corridor.
- **Email Notifications**: Instant email alerts sent to administrators when a student is flagged as "Missing".
- **Dynamic Thresholding**: Configurable time limits for student movement.

### 📺 CCTV Monitor Mode
- **Clean Raw Feed**: Traditional monitor view without detection overlays.
- **Dynamic Status**: Real-time "Active/Offline" status indicators for all hardware.
- **Stability Engine**: Built-in recovery cooldowns and phantom feed prevention.

### 📊 Management Dashboard
- **Glassmorphic UI**: Beautiful, modern administration panel with quick statistics.
- **Attendance Logs**: Daily automated attendance marking.
- **Detailed Reports**: Searchable logs for found and missing student events.

## 🛠️ Tech Stack

- **Backend**: Python, Django
- **Computer Vision**: OpenCV, Face Recognition Library
- **AI/ML**: Ultralytics YOLOv11
- **Frontend**: HTML5, Vanilla CSS (Glassmorphism), JavaScript
- **Database**: SQLite (Development) / PostgreSQL (Production ready)

## ⚙️ Installation & Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/dev-zd/anti-class-bunking-system.git
   cd anti-class-bunking-system
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Settings**
   - Update `EMAIL_SENDER` and `EMAIL_PASSWORD` in `core/camera.py` for alerts.
   - Run migrations:
     ```bash
     python manage.py migrate
     ```

4. **Run the Application**
   ```bash
   python manage.py runserver
   ```

## 📸 Usage Screenshots

> [!TIP]
> Add your own screenshots from the `walkthrough.md` to this section once you have them!

- **Dashboard**: High-level overview of presence and alerts.
- **Live Analysis**: Real-time face identifying and bounding boxes.
- **CCTV Monitor**: Raw dual-camera feed for traditional security.

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
Developed with ❤️ by [dev-zd](https://github.com/dev-zd)
