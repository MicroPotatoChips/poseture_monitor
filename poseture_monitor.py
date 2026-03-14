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
    QHBoxLayout, QComboBox, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

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
        r"C:\\Windows\\Fonts\\msyh.ttc",
        r"C:\\Windows\\Fonts\\msyhbd.ttc",
        r"C:\\Windows\\Fonts\\simhei.ttf",
        r"C:\\Windows\\Fonts\\simsun.ttc",
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
    if mag_ab * mag_cb == 0:
        return 0.0
    cos_angle = max(-1.0, min(1.0, dot / (mag_ab * mag_cb)))
    return math.degrees(math.acos(cos_angle))

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

def angle_to_vertical(a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    dot = vx * 0 + vy * -1
    mag = math.hypot(vx, vy)
    if mag == 0:
        return 0.0
    cos_angle = max(-1.0, min(1.0, dot / mag))
    return math.degrees(math.acos(cos_angle))

def lm_vis(lm):
    return getattr(lm, "visibility", 1.0)

def get_system_camera_names():
    try:
        import win32com.client  # type: ignore
    except Exception:
        return []
    try:
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
        self.setWindowTitle("AI 智能坐姿健康分析系统")
        self.resize(1100, 750)
        
        # 核心变量
        self.cap = None
        self.landmarker = None
        self.running = False
        self.ema_angle = None
        self.ema_forward = None
        self.ema_torso = None
        self.frame_ts = 0
        self.view_mode = "side"
        self.bad_posture_start = None
        self.alerted_in_session = False
        self.bad_posture_accum = 0.0
        self.last_bad_tick = None
        self.last_state = None
        self.last_state_time = 0.0
        self.current_width = 640
        self.current_height = 480
        self.camera_index = 0

        self.init_ui()
        self.apply_stylesheet()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        sound_path = Path(__file__).resolve().parent / "sound.mp3"
        if sound_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(sound_path)))

    def init_ui(self):
        # 主布局：左右分栏
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # ---------------- 左侧：视频显示区 ----------------
        left_panel = QFrame(self)
        left_panel.setObjectName("VideoPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)

        self.video_label = QLabel(self)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #000000; border-radius: 8px;")
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left_layout.addWidget(self.video_label)

        # ---------------- 右侧：控制与数据区 ----------------
        right_panel = QFrame(self)
        right_panel.setObjectName("ControlPanel")
        right_panel.setFixedWidth(320)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(20, 25, 20, 25)
        right_layout.setSpacing(15)

        # 标题栏
        title_label = QLabel("AI 坐姿卫士")
        title_label.setObjectName("TitleLabel")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        subtitle_label = QLabel("守护您的脊椎健康")
        subtitle_label.setObjectName("SubTitleLabel")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 核心数据卡片
        self.status_card = QFrame()
        self.status_card.setObjectName("StatusCard")
        card_layout = QVBoxLayout(self.status_card)
        card_layout.setSpacing(10)
        
        self.status_title = QLabel("实时监测状态")
        self.status_title.setObjectName("CardTitle")
        self.posture_label = QLabel("等待启动...")
        self.posture_label.setObjectName("ResultLabelReady")
        self.posture_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.angle_label = QLabel("前倾角度: --°")
        self.angle_label.setObjectName("DataLabel")
        
        card_layout.addWidget(self.status_title)
        card_layout.addWidget(self.posture_label)
        card_layout.addWidget(self.angle_label)

        # 设置区域
        settings_label = QLabel("视频分辨率设置")
        settings_label.setObjectName("SectionTitle")
        
        self.res_combo = QComboBox()
        self.res_combo.addItems(["标清 (640x480)", "高清 (1280x720)", "超清 (1920x1080)"])
        self.res_combo.currentIndexChanged.connect(self.change_resolution)

        camera_label = QLabel("摄像头设备")
        camera_label.setObjectName("SectionTitle")
        self.camera_combo = QComboBox()
        self.refresh_camera_list()
        self.camera_combo.currentIndexChanged.connect(self.change_camera_device)

        view_label = QLabel("拍摄角度")
        view_label.setObjectName("SectionTitle")
        self.view_combo = QComboBox()
        self.view_combo.addItems(["侧面", "正面"])
        self.view_combo.currentIndexChanged.connect(self.change_view_mode)

        # 操作按钮区
        self.start_btn = QPushButton("▶ 开始监控")
        self.start_btn.setObjectName("PrimaryBtn")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.toggle_monitoring)

        self.quit_btn = QPushButton("退出程序")
        self.quit_btn.setObjectName("DangerBtn")
        self.quit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quit_btn.clicked.connect(self.close)

        tip_label = QLabel("💡 提示：按 ESC 键可快速停止")
        tip_label.setObjectName("TipLabel")
        tip_label.setWordWrap(True)

        # 组装右侧
        right_layout.addWidget(title_label)
        right_layout.addWidget(subtitle_label)
        right_layout.addSpacing(10)
        right_layout.addWidget(self.status_card)
        right_layout.addSpacing(20)
        right_layout.addWidget(settings_label)
        right_layout.addWidget(self.res_combo)
        right_layout.addWidget(camera_label)
        right_layout.addWidget(self.camera_combo)
        right_layout.addWidget(view_label)
        right_layout.addWidget(self.view_combo)
        right_layout.addStretch(1)
        right_layout.addWidget(tip_label)
        right_layout.addWidget(self.start_btn)
        right_layout.addWidget(self.quit_btn)

        # 添加到主布局
        main_layout.addWidget(left_panel, stretch=7)
        main_layout.addWidget(right_panel, stretch=3)

    def apply_stylesheet(self):
        # 现代清新风格 (大厂风 UI)
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
        """
        self.setStyleSheet(style)

    def change_resolution(self, index):
        resolutions = [(640, 480), (1280, 720), (1920, 1080)]
        self.current_width, self.current_height = resolutions[index]
        
        # 如果摄像头正在运行，实时修改分辨率
        if self.running:
            self.restart_capture_for_resolution()

    def refresh_camera_list(self):
        self.camera_combo.clear()
        available = []
        for i in range(6):
            cap = cv2.VideoCapture(i)
            if cap is not None and cap.isOpened():
                available.append(i)
                cap.release()
        if not available:
            available = [0]
        sys_names = get_system_camera_names()
        for idx, i in enumerate(available):
            label = f"设备 {i}"
            if idx < len(sys_names):
                label = f"设备 {i} - {sys_names[idx]}"
            self.camera_combo.addItem(label, i)
        if self.camera_index in available:
            self.camera_combo.setCurrentIndex(available.index(self.camera_index))
        else:
            self.camera_index = available[0]
            self.camera_combo.setCurrentIndex(0)

    def change_camera_device(self, index):
        data = self.camera_combo.itemData(index)
        if data is None:
            return
        self.camera_index = int(data)
        if self.running:
            self.restart_capture_for_resolution()

    def change_view_mode(self, index):
        self.view_mode = "side" if index == 0 else "front"

    def update_alert(self, is_good):
        now = time.monotonic()
        if is_good:
            self.bad_posture_start = None
            self.last_bad_tick = None
            self.bad_posture_accum = 0.0
            self.alerted_in_session = False
            return

        # 累计非正常姿势时长（中断则停止累计，但不清零）
        if self.last_bad_tick is None:
            self.last_bad_tick = now
        else:
            self.bad_posture_accum += (now - self.last_bad_tick)
            self.last_bad_tick = now

        if not self.alerted_in_session and self.bad_posture_accum >= 20:
            if self.player.source().isValid():
                self.player.stop()
                self.player.play()
            self.alerted_in_session = True

    def restart_capture_for_resolution(self):
        # Mediapipe VIDEO running mode requires consistent frame sizes.
        # Safely restart capture + landmarker to avoid crashes on resolution change.
        self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
        self.landmarker = None
        self.frame_ts = 0

        self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.current_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.current_height)

        self.landmarker = create_landmarker()
        self.timer.start(30)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.running:
            self.stop_monitoring()
        super().keyPressEvent(event)

    def toggle_monitoring(self):
        if self.running:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        self.cap = cv2.VideoCapture(self.camera_index)
        # 初始应用选定的分辨率
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.current_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.current_height)
        
        self.landmarker = create_landmarker()
        self.running = True
        self.frame_ts = 0
        self.bad_posture_accum = 0.0
        self.last_bad_tick = None
        self.alerted_in_session = False
        
        self.start_btn.setText("⏹ 停止监控")
        self.start_btn.setStyleSheet("background-color: #EF4444;") # 变成红色
        self.posture_label.setText("正在检测...")
        self.posture_label.setObjectName("ResultLabelGood")
        self.style().unpolish(self.posture_label)
        self.style().polish(self.posture_label)
        
        self.timer.start(30)

    def stop_monitoring(self):
        self.running = False
        self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
            
        self.landmarker = None
        self.ema_angle, self.ema_forward, self.ema_torso = None, None, None
        self.bad_posture_start = None
        self.alerted_in_session = False
        self.bad_posture_accum = 0.0
        self.last_bad_tick = None
        self.last_state = None
        self.last_state_time = 0.0
        
        self.start_btn.setText("▶ 开始监控")
        self.start_btn.setStyleSheet("") # 恢复默认QSS
        self.posture_label.setText("监控已停止")
        self.posture_label.setObjectName("ResultLabelReady")
        self.angle_label.setText("前倾角度: --°")
        self.video_label.clear()
        
        self.style().unpolish(self.posture_label)
        self.style().polish(self.posture_label)

    def update_frame(self):
        if not self.running or not self.cap:
            return

        ret, frame = self.cap.read()
        if not ret:
            self.stop_monitoring()
            return

        # 镜像翻转，更符合用户直觉
        frame = cv2.flip(frame, 1)

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        )
        # Use a monotonic timestamp to avoid crashes on some drivers/resolution switches.
        self.frame_ts += 33
        timestamp = self.frame_ts
            
        result = self.landmarker.detect_for_video(mp_image, timestamp)
        h, w, _ = frame.shape

        posture_issues = []
        is_good = True

        if result.pose_landmarks:
            lm = result.pose_landmarks[0]
            
            # 提取躯干点
            l_ear, r_ear = lm[7], lm[8]
            l_shoulder, r_shoulder = lm[11], lm[12]
            l_hip, r_hip = lm[23], lm[24]

            if self.view_mode == "side":
                # 决定使用可见度高的一侧进行侧面姿态评估
                if lm_vis(l_shoulder) >= lm_vis(r_shoulder):
                    ear, shoulder, hip = l_ear, l_shoulder, l_hip
                else:
                    ear, shoulder, hip = r_ear, r_shoulder, r_hip

                ear_pt = (int(ear.x * w), int(ear.y * h))
                shoulder_pt = (int(shoulder.x * w), int(shoulder.y * h))
                hip_pt = (int(hip.x * w), int(hip.y * h))
                
                # --- 侧面算法：驼背与头前倾 ---
                angle = calc_angle(ear_pt, shoulder_pt, hip_pt)
                torso_tilt = angle_to_vertical(hip_pt, shoulder_pt)
                torso_len = dist(shoulder_pt, hip_pt)
                head_forward_thresh = max(25, int(torso_len * 0.24))
                head_forward = (ear_pt[0] - shoulder_pt[0]) > head_forward_thresh

                # EMA 平滑数据
                alpha = 0.2
                if self.ema_angle is None:
                    self.ema_angle = angle
                    self.ema_forward = 1.0 if head_forward else 0.0
                    self.ema_torso = torso_tilt
                else:
                    self.ema_angle = self.ema_angle * (1 - alpha) + angle * alpha
                    self.ema_forward = self.ema_forward * (1 - alpha) + (1.0 if head_forward else 0.0) * alpha
                    self.ema_torso = self.ema_torso * (1 - alpha) + torso_tilt * alpha

                if self.ema_angle < 150 or self.ema_torso > 28:
                    posture_issues.append("驼背")
                if self.ema_forward > 0.5:
                    posture_issues.append("头前倾")
            else:
                # --- 正面算法：歪肩/歪头/侧倾 ---
                shoulder_y_diff = abs(l_shoulder.y - r_shoulder.y)
                ear_y_diff = abs(l_ear.y - r_ear.y)
                hip_span = max(0.08, math.hypot(l_hip.x - r_hip.x, l_hip.y - r_hip.y))
                mid_shoulder_x = (l_shoulder.x + r_shoulder.x) * 0.5
                mid_hip_x = (l_hip.x + r_hip.x) * 0.5
                lateral_lean = abs(mid_shoulder_x - mid_hip_x)

                if shoulder_y_diff > 0.03:
                    posture_issues.append("歪肩")
                if ear_y_diff > 0.03:
                    posture_issues.append("歪头")
                if lateral_lean > hip_span * 0.12:
                    posture_issues.append("侧倾")

                ear_pt = (int((l_ear.x + r_ear.x) * 0.5 * w), int((l_ear.y + r_ear.y) * 0.5 * h))
                shoulder_pt = (int((l_shoulder.x + r_shoulder.x) * 0.5 * w), int((l_shoulder.y + r_shoulder.y) * 0.5 * h))
                hip_pt = (int((l_hip.x + r_hip.x) * 0.5 * w), int((l_hip.y + r_hip.y) * 0.5 * h))

            # --- 优化算法：从腿部出发检测二郎腿 ---
            # 关键点: 23/24(髋), 25/26(膝), 27/28(踝)
            vis_legs = [lm_vis(lm[i]) for i in (23, 24, 25, 26, 27, 28)]
            if min(vis_legs) > 0.4:  # 确保腿部关键点可见
                l_hip = lm[23]
                r_hip = lm[24]
                l_knee = lm[25]
                r_knee = lm[26]
                l_ankle = lm[27]
                r_ankle = lm[28]

                def ndist(a, b):
                    return math.hypot(a.x - b.x, a.y - b.y)

                hip_span = max(0.08, ndist(l_hip, r_hip))
                l_leg = ndist(l_hip, l_knee) + ndist(l_knee, l_ankle)
                r_leg = ndist(r_hip, r_knee) + ndist(r_knee, r_ankle)
                leg_len = max(0.18, (l_leg + r_leg) * 0.5)

                # 特征1: 脚踝相对膝盖发生左右交叉
                ankle_cross = (l_ankle.x - r_ankle.x) * (l_knee.x - r_knee.x) < 0

                # 特征2: 一侧脚踝靠近对侧膝盖 (典型翘腿)
                ankle_near_opposite_knee = (
                    ndist(l_ankle, r_knee) < leg_len * 0.55 or
                    ndist(r_ankle, l_knee) < leg_len * 0.55
                )

                # 特征3: 一侧脚踝明显抬高到对侧膝盖以上区域
                ankle_high = (l_ankle.y < r_knee.y - 0.03) or (r_ankle.y < l_knee.y - 0.03)

                # 特征4: 膝靠近但踝分离 (交叉坐姿)
                knees_close = ndist(l_knee, r_knee) < hip_span * 0.55
                ankles_far = ndist(l_ankle, r_ankle) > hip_span * 0.65

                if (ankle_cross and (ankle_near_opposite_knee or ankle_high)) or (ankle_cross and knees_close and ankles_far):
                    posture_issues.append("二郎腿")

            # 组装文字（每种状态至少保留 1.5 秒）
            desired_state = "good" if not posture_issues else "bad"
            now = time.monotonic()
            if self.last_state is None:
                self.last_state = desired_state
                self.last_state_time = now
            elif desired_state != self.last_state and (now - self.last_state_time) < 1.5:
                # 保持上一状态
                desired_state = self.last_state
                if desired_state == "bad":
                    posture_issues = ["姿势不正"]
            elif desired_state != self.last_state:
                self.last_state = desired_state
                self.last_state_time = now

            if desired_state == "good":
                posture_text = "姿态良好 ✨"
                label_color = "#10B981" # Green
                box_color = (0, 255, 0)
                self.posture_label.setObjectName("ResultLabelGood")
            else:
                posture_text = " | ".join(posture_issues) + " ⚠️"
                label_color = "#EF4444" # Red
                box_color = (0, 0, 255)
                self.posture_label.setObjectName("ResultLabelBad")
            
            # 更新状态栏
            self.posture_label.setText(posture_text)
            if self.view_mode == "side" and self.ema_angle is not None:
                self.angle_label.setText(f"前倾角度: {int(self.ema_angle)}°")
            else:
                self.angle_label.setText("正面模式")
            
            # 刷新 QSS (使颜色生效)
            self.style().unpolish(self.posture_label)
            self.style().polish(self.posture_label)

            # 在画面上绘制提示
            frame = put_text_cn(frame, posture_text, (20, 20), box_color, 36)
            
            # 绘制骨骼关节点点缀
            cv2.circle(frame, ear_pt, 6, (0, 255, 255), -1)
            cv2.circle(frame, shoulder_pt, 6, (0, 255, 255), -1)
            cv2.circle(frame, hip_pt, 6, (0, 255, 255), -1)

            is_good = (desired_state == "good")
            self.update_alert(is_good)
        else:
            self.update_alert(True)

        # 视频转 QPixmap 显示
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img_q = QImage(frame_rgb.data, frame_rgb.shape[1], frame_rgb.shape[0], frame_rgb.strides[0], QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(img_q)
        
        # 适应 Label 大小
        self.video_label.setPixmap(pixmap.scaled(
            self.video_label.width(),
            self.video_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation # 平滑缩放
        ))

if __name__ == "__main__":
    # Ensure Windows taskbar icon uses the app icon
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "posture_monitor.app"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app_icon_path = Path(__file__).resolve().parent / "icon.ico"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))
    
    # 强制设置字体（防止部分系统默认字体异常）
    font = app.font()
    font.setFamily("Microsoft YaHei")
    app.setFont(font)

    

    win = PostureMonitor()
    win.show()
    sys.exit(app.exec())
