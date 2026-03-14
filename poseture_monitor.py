import sys
import cv2
import mediapipe as mp
import math
import time
from pathlib import Path
import tempfile
import shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageQt

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, 
    QHBoxLayout, QComboBox, QFrame, QSizePolicy, QAbstractButton
)
from PyQt6.QtCore import Qt, QTimer, QUrl, QPropertyAnimation, QRect, pyqtProperty, QEasingCurve, QPoint, QSize
from PyQt6.QtGui import QPixmap, QImage, QIcon, QPainter, QColor
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# ---------------- 语言包定义 ----------------
LANG_DATA = {
    "zh": {
        "title": "AI 智能坐姿健康分析系统",
        "app_name": "AI 坐姿卫士",
        "subtitle": "守护您的脊椎健康",
        "status_title": "实时监测状态",
        "ready": "等待启动...",
        "monitoring": "正在检测...",
        "stopped": "监控已停止",
        "angle": "前倾角度",
        "front_mode": "正面模式",
        "res_label": "视频分辨率设置",
        "cam_label": "摄像头设备",
        "view_label": "拍摄角度",
        "start": "▶ 开始监控",
        "stop": "⏹ 停止监控",
        "quit": "退出程序",
        "tip": "💡 提示：按 ESC 键可快速停止",
        "side": "侧面",
        "front": "正面",
        "good": "姿态良好 ✨",
        "issues": {"hunchback": "驼背", "forward": "头前倾", "shoulder": "歪肩", "head": "歪头", "lean": "侧倾", "cross_legs": "二郎腿", "unknown": "姿势不正"}
    },
    "en": {
        "title": "AI Posture Health Monitor",
        "app_name": "AI Posture Guard",
        "subtitle": "Protect Your Spine Health",
        "status_title": "Real-time Status",
        "ready": "Ready to Start...",
        "monitoring": "Monitoring...",
        "stopped": "Stopped",
        "angle": "Lean Angle",
        "front_mode": "Front Mode",
        "res_label": "Resolution Settings",
        "cam_label": "Camera Device",
        "view_label": "Camera Angle",
        "start": "▶ Start Monitor",
        "stop": "⏹ Stop Monitor",
        "quit": "Quit",
        "tip": "💡 Tip: Press ESC to stop quickly",
        "side": "Side View",
        "front": "Front View",
        "good": "Good Posture ✨",
        "issues": {"hunchback": "Slumping", "forward": "Forward Head", "shoulder": "Uneven Shoulder", "head": "Tilted Head", "lean": "Lateral Lean", "cross_legs": "Crossed Legs", "unknown": "Bad Posture"}
    }
}

class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(60, 28)
        self._thumb_pos = 3
        self.animation = QPropertyAnimation(self, b"thumb_pos")
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    @pyqtProperty(int)
    def thumb_pos(self): return self._thumb_pos
    @thumb_pos.setter
    def thumb_pos(self, pos):
        self._thumb_pos = pos
        self.update()

    def nextCheckState(self):
        super().nextCheckState()
        end_pos = 35 if self.isChecked() else 3
        self.animation.setEndValue(end_pos)
        self.animation.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg_color = QColor("#3B82F6") if self.isChecked() else QColor("#D1D5DB")
        p.setBrush(bg_color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 14, 14)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(self._thumb_pos, 3, 22, 22)
        p.setPen(QColor("#FFFFFF") if self.isChecked() else QColor("#4B5563"))
        font = p.font()
        font.setPixelSize(10)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRect(0,0,self.width(),self.height()), Qt.AlignmentFlag.AlignCenter, "EN" if self.isChecked() else "CN")

MODEL_PATH = str(Path(__file__).resolve().parent / "pose_landmarker_lite.task")

def get_model_path_ascii():
    try:
        MODEL_PATH.encode("ascii")
        return MODEL_PATH
    except UnicodeEncodeError:
        tmp_dir = Path(tempfile.gettempdir()) / "mp_models"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        model_path_ascii = str(tmp_dir / "pose_landmarker_lite.task")
        if not Path(model_path_ascii).exists():
            shutil.copyfile(MODEL_PATH, model_path_ascii)
        return model_path_ascii

def create_landmarker():
    BaseOptions, PoseLandmarker, PoseLandmarkerOptions, VisionRunningMode = python.BaseOptions, vision.PoseLandmarker, vision.PoseLandmarkerOptions, vision.RunningMode
    options = PoseLandmarkerOptions(base_options=BaseOptions(model_asset_path=get_model_path_ascii()), running_mode=VisionRunningMode.VIDEO)
    return PoseLandmarker.create_from_options(options)

def load_chinese_font(size=32):
    candidates = [r"C:\\Windows\\Fonts\\msyh.ttc", r"C:\\Windows\\Fonts\\msyhbd.ttc", r"C:\\Windows\\Fonts\\simhei.ttf", r"C:\\Windows\\Fonts\\simsun.ttc"]
    for path in candidates:
        if Path(path).exists(): return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()

_cn_font = load_chinese_font(32)

def put_text_cn(img_bgr, text, org, color=(0, 0, 255), size=32):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(pil_img)
    font = _cn_font if size == 32 else load_chinese_font(size)
    draw.text(org, text, font=font, fill=(color[2], color[1], color[0]))
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

def calc_angle(a, b, c):
    ab, cb = (a[0]-b[0], a[1]-b[1]), (c[0]-b[0], c[1]-b[1])
    dot = ab[0]*cb[0] + ab[1]*cb[1]
    mag_ab, mag_cb = math.hypot(*ab), math.hypot(*cb)
    if mag_ab * mag_cb == 0: return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / (mag_ab * mag_cb)))))

def dist(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])

def angle_to_vertical(a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    mag = math.hypot(vx, vy)
    if mag == 0: return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (vy * -1) / mag))))

def lm_vis(lm): return getattr(lm, "visibility", 1.0)

def get_system_camera_names():
    try:
        import win32com.client
        locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        service = locator.ConnectServer(".", "root\\cimv2")
        items = service.ExecQuery("SELECT * FROM Win32_PnPEntity WHERE PNPClass='Camera' OR PNPClass='Image'")
        return [getattr(item, "Name", "") for item in items if getattr(item, "Name", None)]
    except: return []

class PostureMonitor(QWidget):
    def __init__(self):
        super().__init__()
        self.lang = "zh"
        self.setWindowTitle(LANG_DATA[self.lang]["title"])
        self.resize(1100, 750)
        self.cap = self.landmarker = None
        self.running = False
        self.ema_angle = self.ema_forward = self.ema_torso = None
        self.frame_ts = 0
        self.view_mode = "side"
        
        # 核心修复部分：
        self.bad_posture_accum = 0.0
        self.last_bad_tick = None
        self.last_state = None
        self.last_state_time = 0.0
        self.alerted_in_session = False  # 初始化报警状态标识
        
        self.current_width, self.current_height, self.camera_index = 640, 480, 0

        

        self.init_ui()
        self.apply_stylesheet()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)

        left_panel = QFrame(self); left_panel.setObjectName("VideoPanel")
        left_layout = QVBoxLayout(left_panel)
        self.video_label = QLabel(self)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #000000; border-radius: 8px;")
        left_layout.addWidget(self.video_label)

        right_panel = QFrame(self); right_panel.setObjectName("ControlPanel")
        right_panel.setFixedWidth(320)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(20, 25, 20, 25)

        self.title_label = QLabel(LANG_DATA[self.lang]["app_name"])
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label = QLabel(LANG_DATA[self.lang]["subtitle"])
        self.subtitle_label.setObjectName("SubTitleLabel")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 语言切换放在subtitle下方
        lang_layout = QHBoxLayout()
        lang_layout.addStretch()
        self.lang_switch = ToggleSwitch()
        self.lang_switch.toggled.connect(self.toggle_language)
        lang_layout.addWidget(self.lang_switch)
        lang_layout.addStretch()

        self.status_card = QFrame(); self.status_card.setObjectName("StatusCard")
        card_layout = QVBoxLayout(self.status_card)
        self.status_title = QLabel(LANG_DATA[self.lang]["status_title"]); self.status_title.setObjectName("CardTitle")
        self.posture_label = QLabel(LANG_DATA[self.lang]["ready"]); self.posture_label.setObjectName("ResultLabelReady")
        self.posture_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.angle_label = QLabel(f"{LANG_DATA[self.lang]['angle']}: --°"); self.angle_label.setObjectName("DataLabel")
        card_layout.addWidget(self.status_title); card_layout.addWidget(self.posture_label); card_layout.addWidget(self.angle_label)

        self.settings_label = QLabel(LANG_DATA[self.lang]["res_label"]); self.settings_label.setObjectName("SectionTitle")
        self.res_combo = QComboBox()
        self.res_combo.addItems(["标清 (640x480)", "高清 (1280x720)", "超清 (1920x1080)"])
        self.res_combo.currentIndexChanged.connect(self.change_resolution)

        self.camera_label = QLabel(LANG_DATA[self.lang]["cam_label"]); self.camera_label.setObjectName("SectionTitle")
        self.camera_combo = QComboBox(); self.refresh_camera_list()
        self.camera_combo.currentIndexChanged.connect(self.change_camera_device)

        self.view_label_text = QLabel(LANG_DATA[self.lang]["view_label"]); self.view_label_text.setObjectName("SectionTitle")
        self.view_combo = QComboBox(); self.update_view_combo_text()
        self.view_combo.currentIndexChanged.connect(self.change_view_mode)

        self.start_btn = QPushButton(LANG_DATA[self.lang]["start"]); self.start_btn.setObjectName("PrimaryBtn")
        self.quit_btn = QPushButton(LANG_DATA[self.lang]["quit"]); self.quit_btn.setObjectName("DangerBtn")
        self.tip_label = QLabel(LANG_DATA[self.lang]["tip"]); self.tip_label.setObjectName("TipLabel")

        right_layout.addWidget(self.title_label); right_layout.addWidget(self.subtitle_label)
        right_layout.addLayout(lang_layout) # 移动到这里
        right_layout.addSpacing(10); right_layout.addWidget(self.status_card); right_layout.addSpacing(20)
        right_layout.addWidget(self.settings_label); right_layout.addWidget(self.res_combo)
        right_layout.addWidget(self.camera_label); right_layout.addWidget(self.camera_combo)
        right_layout.addWidget(self.view_label_text); right_layout.addWidget(self.view_combo)
        right_layout.addStretch(1); right_layout.addWidget(self.tip_label); right_layout.addWidget(self.start_btn); right_layout.addWidget(self.quit_btn)

        main_layout.addWidget(left_panel, stretch=7); main_layout.addWidget(right_panel, stretch=3)
        self.start_btn.clicked.connect(self.toggle_monitoring); self.quit_btn.clicked.connect(self.close)

    def toggle_language(self, checked):
        self.lang = "en" if checked else "zh"
        L = LANG_DATA[self.lang]
        self.setWindowTitle(L["title"]); self.title_label.setText(L["app_name"]); self.subtitle_label.setText(L["subtitle"])
        self.status_title.setText(L["status_title"]); self.settings_label.setText(L["res_label"])
        self.camera_label.setText(L["cam_label"]); self.view_label_text.setText(L["view_label"])
        self.quit_btn.setText(L["quit"]); self.tip_label.setText(L["tip"])
        self.update_view_combo_text()
        if not self.running:
            self.start_btn.setText(L["start"]); self.posture_label.setText(L["ready"])
            self.angle_label.setText(f"{L['angle']}: --°")
        else: self.start_btn.setText(L["stop"])

    def update_view_combo_text(self):
        curr = self.view_combo.currentIndex()
        self.view_combo.blockSignals(True); self.view_combo.clear()
        self.view_combo.addItems([LANG_DATA[self.lang]["side"], LANG_DATA[self.lang]["front"]])
        self.view_combo.setCurrentIndex(curr if curr >= 0 else 0); self.view_combo.blockSignals(False)

    def apply_stylesheet(self):
        self.setStyleSheet("""
            QWidget { font-family: 'Microsoft YaHei'; background-color: #F0F2F5; }
            #VideoPanel, #ControlPanel { background-color: #FFFFFF; border-radius: 12px; border: 1px solid #E5E7EB; }
            #TitleLabel { font-size: 26px; font-weight: bold; color: #111827; }
            #SubTitleLabel { font-size: 14px; color: #6B7280; }
            #StatusCard { background-color: #F9FAFB; border-radius: 8px; border: 1px solid #E5E7EB; padding: 10px; }
            #CardTitle { font-size: 13px; font-weight: bold; color: #6B7280; }
            #ResultLabelReady { font-size: 20px; font-weight: bold; color: #9CA3AF; padding: 15px 0; }
            #ResultLabelGood { font-size: 20px; font-weight: bold; color: #10B981; padding: 15px 0; }
            #ResultLabelBad { font-size: 20px; font-weight: bold; color: #EF4444; padding: 15px 0; }
            #DataLabel { font-size: 14px; color: #374151; }
            #SectionTitle { font-size: 14px; font-weight: bold; color: #374151; margin-top: 10px; }
            QComboBox { padding: 8px 12px; border: 1px solid #D1D5DB; border-radius: 6px; background-color: #FFFFFF; font-size: 14px; }
            QComboBox::drop-down { border: none; width: 0px; } 
            QComboBox::down-arrow { image: none; }
            #PrimaryBtn { background-color: #3B82F6; color: #FFFFFF; font-size: 16px; font-weight: bold; padding: 12px; border-radius: 8px; border: none; }
            #DangerBtn { background-color: transparent; color: #EF4444; font-size: 15px; padding: 10px; border-radius: 8px; border: 1px solid #EF4444; }
            #TipLabel { color: #9CA3AF; font-size: 12px; margin-bottom: 10px; }
        """)

    def change_resolution(self, index):
        self.current_width, self.current_height = [(640, 480), (1280, 720), (1920, 1080)][index]
        if self.running: self.restart_capture_for_resolution()

    def refresh_camera_list(self):
        self.camera_combo.clear(); avail = []
        for i in range(3):
            c = cv2.VideoCapture(i)
            if c and c.isOpened(): avail.append(i); c.release()
        names = get_system_camera_names()
        for i in (avail or [0]): self.camera_combo.addItem(f"{(names[i] if i<len(names) else 'Device '+str(i))}", i)

    def change_camera_device(self, index):
        data = self.camera_combo.itemData(index)
        if data is not None:
            self.camera_index = int(data)
            if self.running: self.restart_capture_for_resolution()

    def change_view_mode(self, index): self.view_mode = "side" if index == 0 else "front"

    def update_alert(self, is_good):
        now = time.monotonic()
        if is_good:
            self.last_bad_tick = None; self.bad_posture_accum = 0.0; self.alerted_in_session = False; return
        if self.last_bad_tick is None: self.last_bad_tick = now
        else: self.bad_posture_accum += (now - self.last_bad_tick); self.last_bad_tick = now
        
        if not self.alerted_in_session and self.bad_posture_accum >= 20:
            fname = "sound_en.mp3" if self.lang == "en" else "sound.mp3"
            s_path = Path(__file__).resolve().parent / fname
            if s_path.exists():
                self.player.setSource(QUrl.fromLocalFile(str(s_path)))
                self.player.play()
                self.alerted_in_session = True

    def restart_capture_for_resolution(self):
        self.timer.stop()
        if self.cap: self.cap.release()
        self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.current_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.current_height)
        self.landmarker = create_landmarker()
        self.frame_ts = 0; self.timer.start(30)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.running: self.stop_monitoring()

    def toggle_monitoring(self): self.stop_monitoring() if self.running else self.start_monitoring()

    def start_monitoring(self):
        self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.current_width); self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.current_height)
        self.landmarker = create_landmarker(); self.running = True; self.frame_ts = 0; self.bad_posture_accum = 0.0
        self.start_btn.setText(LANG_DATA[self.lang]["stop"]); self.start_btn.setStyleSheet("background-color: #EF4444;")
        self.posture_label.setText(LANG_DATA[self.lang]["monitoring"]); self.timer.start(30)

    def stop_monitoring(self):
        self.running = False; self.timer.stop()
        if self.cap: self.cap.release()
        self.cap = self.landmarker = self.ema_angle = self.ema_forward = self.ema_torso = None
        self.start_btn.setText(LANG_DATA[self.lang]["start"]); self.start_btn.setStyleSheet("")
        self.posture_label.setText(LANG_DATA[self.lang]["stopped"]); self.posture_label.setObjectName("ResultLabelReady")
        self.angle_label.setText(f"{LANG_DATA[self.lang]['angle']}: --°"); self.video_label.clear()
        self.style().unpolish(self.posture_label); self.style().polish(self.posture_label)

    def update_frame(self):
        if not self.running or not self.cap: return
        ret, frame = self.cap.read()
        if not ret: self.stop_monitoring(); return
        frame = cv2.flip(frame, 1)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        self.frame_ts += 33
        res = self.landmarker.detect_for_video(mp_img, self.frame_ts)
        h, w, issues, L = frame.shape[0], frame.shape[1], [], LANG_DATA[self.lang]
        if res.pose_landmarks:
            lm = res.pose_landmarks[0]
            l_e, r_e, l_s, r_s, l_h, r_h = lm[7], lm[8], lm[11], lm[12], lm[23], lm[24]
            if self.view_mode == "side":
                side = "l" if lm_vis(l_s) >= lm_vis(r_s) else "r"
                ear, sh, hip = (l_e, l_s, l_h) if side == "l" else (r_e, r_s, r_h)
                e_p, s_p, h_p = (int(ear.x*w), int(ear.y*h)), (int(sh.x*w), int(sh.y*h)), (int(hip.x*w), int(hip.y*h))
                angle, tilt = calc_angle(e_p, s_p, h_p), angle_to_vertical(h_p, s_p)
                fwd = (e_p[0]-s_p[0]) > max(25, int(dist(s_p, h_p)*0.24))
                if self.ema_angle is None: self.ema_angle, self.ema_forward, self.ema_torso = angle, float(fwd), tilt
                else: 
                    self.ema_angle = self.ema_angle*0.8 + angle*0.2
                    self.ema_forward = self.ema_forward*0.8 + float(fwd)*0.2
                    self.ema_torso = self.ema_torso*0.8 + tilt*0.2
                if self.ema_angle < 150 or self.ema_torso > 28: issues.append(L["issues"]["hunchback"])
                if self.ema_forward > 0.5: issues.append(L["issues"]["forward"])
            else:
                if abs(l_s.y-r_s.y)>0.03: issues.append(L["issues"]["shoulder"])
                if abs(l_e.y-r_e.y)>0.03: issues.append(L["issues"]["head"])
                e_p, s_p, h_p = (int((l_e.x+r_e.x)*.5*w), int((l_e.y+r_e.y)*.5*h)), (int((l_s.x+r_s.x)*.5*w), int((l_s.y+r_s.y)*.5*h)), (int((l_h.x+r_h.x)*.5*w), int((l_h.y+r_h.y)*.5*h))
            
            now, desired = time.monotonic(), ("good" if not issues else "bad")
            if self.last_state is None or (desired != self.last_state and (now-self.last_state_time)>1.5):
                self.last_state, self.last_state_time = desired, now
            else: desired = self.last_state
            
            p_t = L["good"] if desired == "good" else (" | ".join(issues or [L["issues"]["unknown"]]) + " ⚠️")
            self.posture_label.setText(p_t); self.posture_label.setObjectName("ResultLabelGood" if desired=="good" else "ResultLabelBad")
            self.angle_label.setText(f"{L['angle']}: {int(self.ema_angle)}°" if self.view_mode=="side" and self.ema_angle else L["front_mode"])
            self.style().unpolish(self.posture_label); self.style().polish(self.posture_label)
            frame = put_text_cn(frame, p_t, (20,20), (0,255,0) if desired=="good" else (0,0,255), 36)
            for pt in [e_p, s_p, h_p]: cv2.circle(frame, pt, 6, (0,255,255), -1)
            self.update_alert(desired=="good")
        else: self.update_alert(True)
        q_img = QImage(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).data, w, h, w*3, QImage.Format.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(q_img).scaled(self.video_label.width(), self.video_label.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(app.font())
    win = PostureMonitor(); win.show()
    sys.exit(app.exec())
