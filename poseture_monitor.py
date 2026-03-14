import sys
import cv2
import mediapipe as mp
import math
import time
from pathlib import Path
import tempfile
import shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, 
    QHBoxLayout, QComboBox, QFrame, QSizePolicy, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# 模型路径配置
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
    BaseOptions = python.BaseOptions
    PoseLandmarker = vision.PoseLandmarker
    PoseLandmarkerOptions = vision.PoseLandmarkerOptions
    VisionRunningMode = vision.RunningMode

    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=get_model_path_ascii()),
        running_mode=VisionRunningMode.VIDEO
    )
    return PoseLandmarker.create_from_options(options)

def load_chinese_font(size=32):
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
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
    ab = (a[0] - b[0], a[1] - b[1])
    cb = (c[0] - b[0], c[1] - b[1])
    dot = ab[0] * cb[0] + ab[1] * cb[1]
    mag_ab = math.hypot(*ab)
    mag_cb = math.hypot(*cb)
    if mag_ab * mag_cb == 0: return 0.0
    cos_angle = max(-1.0, min(1.0, dot / (mag_ab * mag_cb)))
    return math.degrees(math.acos(cos_angle))

def angle_to_vertical(a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    dot = vy * -1
    mag = math.hypot(vx, vy)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / mag)))) if mag != 0 else 0.0

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

def lm_vis(lm):
    return getattr(lm, "visibility", 1.0)

def get_system_camera_names():
    try:
        import win32com.client  # type: ignore
        locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        service = locator.ConnectServer(".", "root\\cimv2")
        items = service.ExecQuery(
            "SELECT * FROM Win32_PnPEntity WHERE PNPClass='Camera' OR PNPClass='Image'"
        )
        names = []
        for item in items:
            name = getattr(item, "Name", None)
            if name and name not in names:
                names.append(name)
        return names
    except Exception:
        return []


class PostureMonitor(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Posture Monitor")
        icon_path = Path(__file__).resolve().parent / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1100, 750)

        # 核心变量
        self.lang = "zh"
        self.lang = "zh"
        self.i18n = {
            "zh": {
                "window_title": "AI ??????????",
                "title": "AI ????",
                "subtitle": "????????",
                "status_title": "??????",
                "status_idle": "????...",
                "status_running": "????...",
                "status_stopped": "?????",
                "angle_idle": "????: --?",
                "angle_prefix": "????: ",
                "settings": "???????",
                "camera": "?????",
                "view": "????",
                "res_items": ["?? (640x480)", "?? (1280x720)", "?? (1920x1080)"],
                "view_items": ["??", "??"],
                "start": "? ????",
                "stop": "? ????",
                "quit": "????",
                "tip": "?? ???? ESC ??????",
                "front_mode": "????",
                "good": "???? ?",
                "bad_generic": "????",
                "issue_hunch": "??",
                "issue_head_forward": "???",
                "issue_cross_leg": "???",
                "issue_uneven_shoulder": "??",
                "issue_tilt_head": "??",
                "issue_lean": "??",
                "language": "??"
            },
            "en": {
                "window_title": "AI Posture Monitor",
                "title": "AI Posture Guard",
                "subtitle": "Protect your spine health",
                "status_title": "Live Status",
                "status_idle": "Ready to start...",
                "status_running": "Detecting...",
                "status_stopped": "Monitoring stopped",
                "angle_idle": "Front tilt: --?",
                "angle_prefix": "Front tilt: ",
                "settings": "Video Resolution",
                "camera": "Camera Device",
                "view": "View Angle",
                "res_items": ["SD (640x480)", "HD (1280x720)", "FHD (1920x1080)"],
                "view_items": ["Side", "Front"],
                "start": "? Start",
                "stop": "? Stop",
                "quit": "Quit",
                "tip": "?? Tip: Press ESC to stop",
                "front_mode": "Front mode",
                "good": "Good posture ?",
                "bad_generic": "Bad posture",
                "issue_hunch": "Hunched back",
                "issue_head_forward": "Head forward",
                "issue_cross_leg": "Leg crossing",
                "issue_uneven_shoulder": "Uneven shoulders",
                "issue_tilt_head": "Head tilt",
                "issue_lean": "Side lean",
                "language": "Language"
            }
        }
        self.cap = None
        self.landmarker = None
        self.running = False
        self.ema_angle, self.ema_forward, self.ema_torso = None, None, None
        self.frame_ts = 0
        self.view_mode = "side"
        self.bad_posture_accum = 0.0
        self.last_bad_tick = None
        self.last_state = None
        self.last_state_time = 0.0
        self.current_width, self.current_height = 640, 480
        self.camera_index = 0

        self.init_ui()
        self.apply_stylesheet()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)

        self.audio_output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        sound_path = Path(__file__).resolve().parent / "sound.mp3"
        if sound_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(sound_path)))

    def t(self, key):
        return self.i18n.get(self.lang, {}).get(key, key)

    def init_ui(self):
        self.resize(1100, 750)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # 左侧：视频显示
        left_panel = QFrame()
        left_panel.setObjectName("VideoPanel")
        left_layout = QVBoxLayout(left_panel)
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #000; border-radius: 8px;")
        left_layout.addWidget(self.video_label)

        # 右侧：控制面板
        right_panel = QFrame()
        right_panel.setObjectName("ControlPanel")
        right_panel.setFixedWidth(320)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(20, 25, 20, 25)
        right_layout.setSpacing(15)

        self.title_label = QLabel()
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("SubTitleLabel")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 语言切换 (胶囊开关设计)
        lang_row = QFrame()
        lang_lay = QHBoxLayout(lang_row)
        lang_lay.setContentsMargins(0, 0, 0, 0)
        self.lang_label = QLabel()
        self.lang_label.setObjectName("SectionTitle")
        self.lang_toggle = QCheckBox()
        self.lang_toggle.setObjectName("LangToggle")
        self.lang_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_toggle.stateChanged.connect(self.change_language)
        self.lang_cn_hint = QLabel("中")
        self.lang_en_hint = QLabel("EN")
        self.lang_cn_hint.setObjectName("TipLabel")
        self.lang_en_hint.setObjectName("TipLabel")
        
        lang_lay.addWidget(self.lang_label)
        lang_lay.addStretch()
        lang_lay.addWidget(self.lang_cn_hint)
        lang_lay.addWidget(self.lang_toggle)
        lang_lay.addWidget(self.lang_en_hint)

        # 状态卡片
        self.status_card = QFrame()
        self.status_card.setObjectName("StatusCard")
        card_lay = QVBoxLayout(self.status_card)
        self.status_title = QLabel()
        self.status_title.setObjectName("CardTitle")
        self.posture_label = QLabel()
        self.posture_label.setObjectName("ResultLabelReady")
        self.posture_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.angle_label = QLabel()
        self.angle_label.setObjectName("DataLabel")
        card_lay.addWidget(self.status_title)
        card_lay.addWidget(self.posture_label)
        card_lay.addWidget(self.angle_label)

        # 配置项
        self.settings_label = QLabel()
        self.settings_label.setObjectName("SectionTitle")
        self.res_combo = QComboBox()
        self.res_combo.currentIndexChanged.connect(self.change_resolution)

        self.camera_label = QLabel()
        self.camera_label.setObjectName("SectionTitle")
        self.camera_combo = QComboBox()
        self.camera_combo.currentIndexChanged.connect(self.change_camera)

        self.view_label = QLabel()
        self.view_label.setObjectName("SectionTitle")
        self.view_combo = QComboBox()
        self.view_combo.currentIndexChanged.connect(self.change_view_mode)

        # 底部按钮
        self.start_btn = QPushButton()
        self.start_btn.setObjectName("PrimaryBtn")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.toggle_monitoring)

        self.quit_btn = QPushButton()
        self.quit_btn.setObjectName("DangerBtn")
        self.quit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quit_btn.clicked.connect(self.close)

        self.tip_label = QLabel()
        self.tip_label.setObjectName("TipLabel")
        self.tip_label.setWordWrap(True)

        right_layout.addWidget(self.title_label)
        right_layout.addWidget(self.subtitle_label)
        right_layout.addWidget(lang_row)
        right_layout.addSpacing(10)
        right_layout.addWidget(self.status_card)
        right_layout.addSpacing(15)
        right_layout.addWidget(self.settings_label)
        right_layout.addWidget(self.res_combo)
        right_layout.addWidget(self.camera_label)
        right_layout.addWidget(self.camera_combo)
        right_layout.addWidget(self.view_label)
        right_layout.addWidget(self.view_combo)
        right_layout.addStretch(1)
        right_layout.addWidget(self.tip_label)
        right_layout.addWidget(self.start_btn)
        right_layout.addWidget(self.quit_btn)

        main_layout.addWidget(left_panel, 7)
        main_layout.addWidget(right_panel, 3)
        
        self.refresh_camera_list()
        self.apply_language()

    def apply_stylesheet(self):
        style = """
       
        QWidget {
            font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            background-color: #F0F2F5;
        }
        #VideoPanel, #ControlPanel {
            background-color: #FFFFFF;
            border-radius: 12px;
            border: 1px solid #E5E7EB;
        }
        #TitleLabel {
            font-size: 26px;
            font-weight: bold;
            color: #111827;
        }
        #SubTitleLabel {
            font-size: 14px;
            color: #6B7280;
        }
        #StatusCard {
            background-color: #F9FAFB;
            border-radius: 8px;
            border: 1px solid #E5E7EB;
            padding: 10px;
        }
        #CardTitle {
            font-size: 13px;
            font-weight: bold;
            color: #6B7280;
        }
        #ResultLabelReady {
            font-size: 22px;
            font-weight: bold;
            color: #9CA3AF;
            padding: 15px 0;
        }
        #ResultLabelGood {
            font-size: 22px;
            font-weight: bold;
            color: #10B981;  /* 绿色 */
            padding: 15px 0;
        }
        #ResultLabelBad {
            font-size: 22px;
            font-weight: bold;
            color: #EF4444;  /* 红色 */
            padding: 15px 0;
        }
        #DataLabel {
            font-size: 14px;
            color: #374151;
        }
        #SectionTitle {
            font-size: 14px;
            font-weight: bold;
            color: #374151;
            margin-top: 10px;
        }
        QComboBox {
            padding: 8px 12px;
            border: 1px solid #D1D5DB;
            border-radius: 6px;
            background-color: #FFFFFF;
            font-size: 14px;
            color: #374151;
        }
        QComboBox::drop-down {
            border: none;
        }
        #PrimaryBtn {
            background-color: #3B82F6;
            color: #FFFFFF;
            font-size: 16px;
            font-weight: bold;
            padding: 12px;
            border-radius: 8px;
            border: none;
        }
        #PrimaryBtn:hover { background-color: #2563EB; }
        #PrimaryBtn:pressed { background-color: #1D4ED8; }
        
        #DangerBtn {
            background-color: transparent;
            color: #EF4444;
            font-size: 15px;
            padding: 10px;
            border-radius: 8px;
            border: 1px solid #EF4444;
        }
        #DangerBtn:hover {
            background-color: #FEF2F2;
        }
        #TipLabel {
            color: #9CA3AF;
            font-size: 12px;
            margin-bottom: 10px;
        }

        /* 胶囊形状 CheckBox 样式 */
        #LangToggle::indicator { width: 36px; height: 18px; border-radius: 9px; }
        #LangToggle::indicator:unchecked { background-color: #D1D5DB; border: 1px solid #9CA3AF; }
        #LangToggle::indicator:checked { background-color: #10B981; border: 1px solid #059669; }
        """
        self.setStyleSheet(style)

    def change_language(self, state):
        self.lang = "en" if state == Qt.CheckState.Checked.value else "zh"
        self.apply_language()

    def apply_language(self):
        self.lang_toggle.blockSignals(True)
        self.lang_toggle.setChecked(self.lang == "en")
        self.lang_toggle.blockSignals(False)

        self.setWindowTitle(self.t("window_title"))
        self.title_label.setText(self.t("title"))
        self.subtitle_label.setText(self.t("subtitle"))
        self.status_title.setText(self.t("status_title"))
        self.settings_label.setText(self.t("settings"))
        self.camera_label.setText(self.t("camera"))
        self.view_label.setText(self.t("view"))
        self.tip_label.setText(self.t("tip"))
        self.lang_label.setText(self.t("language"))
        self.quit_btn.setText(self.t("quit"))

        # 下拉框重刷
        for combo, key in [(self.res_combo, "res_items"), (self.view_combo, "view_items")]:
            idx = combo.currentIndex()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self.t(key))
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)

        # 按钮与标签
        if self.running:
            self.start_btn.setText(self.t("stop"))
        else:
            self.start_btn.setText(self.t("start"))
            self.posture_label.setText(self.t("status_idle"))
            self.angle_label.setText(self.t("angle_idle"))

    def refresh_camera_list(self):
        self.camera_combo.clear()
        available = []
        for i in range(6):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available.append(i)
                cap.release()
        if not available:
            available = [0]

        names = get_system_camera_names()
        for idx, i in enumerate(available):
            label = f"设备 {i}"
            if idx < len(names):
                label = f"设备 {i} - {names[idx]}"
            self.camera_combo.addItem(label, i)

        if self.camera_index in available:
            self.camera_combo.setCurrentIndex(available.index(self.camera_index))
        else:
            self.camera_index = available[0]
            self.camera_combo.setCurrentIndex(0)


    def toggle_monitoring(self):
        if self.running: self.stop_monitoring()
        else: self.start_monitoring()

    def start_monitoring(self):
        if self.cap:
            self.cap.release()
            self.cap = None
        self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.current_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.current_height)
        self.landmarker = create_landmarker()
        self.running = True
        self.timer.start(30)
        self.start_btn.setText(self.t("stop"))
        self.start_btn.setStyleSheet("background-color: #EF4444;")
        self.posture_label.setObjectName("ResultLabelGood")

    def stop_monitoring(self):
        self.running = False
        self.timer.stop()
        self.landmarker = None
        if self.cap:
            self.cap.release()
            self.cap = None
        self.video_label.clear()
        self.start_btn.setStyleSheet("")
        self.apply_language()

    def change_resolution(self, idx):
        res = [(640, 480), (1280, 720), (1920, 1080)]
        self.current_width, self.current_height = res[idx]
        if self.running: self.start_monitoring()

    def change_camera(self, idx):
        self.camera_index = self.camera_combo.itemData(idx)
        if self.running:
            self.stop_monitoring()
            self.start_monitoring()

    def change_view_mode(self, idx):
        self.view_mode = "side" if idx == 0 else "front"

    def update_frame(self):
        if not self.running or not self.cap: return
        ret, frame = self.cap.read()
        if not ret: return
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        self.frame_ts += 33
        result = self.landmarker.detect_for_video(mp_image, self.frame_ts)

        posture_issues = []
        if result.pose_landmarks:
            lm = result.pose_landmarks[0]
            if self.view_mode == "side":
                # 侧面检测逻辑...
                ear, sho, hip = lm[7], lm[11], lm[23]
                ear_pt, sho_pt, hip_pt = (int(ear.x*w), int(ear.y*h)), (int(sho.x*w), int(sho.y*h)), (int(hip.x*w), int(hip.y*h))
                ang = calc_angle(ear_pt, sho_pt, hip_pt)
                self.ema_angle = ang if self.ema_angle is None else self.ema_angle*0.8 + ang*0.2
                if self.ema_angle < 150: posture_issues.append(self.t("issue_hunch"))
                self.angle_label.setText(f"{self.t('angle_prefix')}{int(self.ema_angle)}°")
            else:
                self.angle_label.setText(self.t("front_mode"))
                if abs(lm[11].y - lm[12].y) > 0.04: posture_issues.append(self.t("issue_uneven_shoulder"))

            # 更新 UI 文字与颜色
            if not posture_issues:
                self.posture_label.setText(self.t("good"))
                self.posture_label.setObjectName("ResultLabelGood")
                box_color = (0, 255, 0)
            else:
                self.posture_label.setText(" | ".join(posture_issues))
                self.posture_label.setObjectName("ResultLabelBad")
                box_color = (0, 0, 255)

            frame = put_text_cn(frame, self.posture_label.text(), (20, 20), box_color, 36)
            self.style().unpolish(self.posture_label)
            self.style().polish(self.posture_label)

        img_q = QImage(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).data, w, h, w*3, QImage.Format.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(img_q).scaled(self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PostureMonitor()
    win.show()
    # Ensure Windows taskbar icon uses the app icon
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "posture_monitor.app"
            )
        except Exception:
            pass

    
    app_icon_path = Path(__file__).resolve().parent / "icon.ico"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))
    sys.exit(app.exec())
